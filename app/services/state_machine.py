from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import DAILY, ENTRY_TRENDS, HOUR_60, STRUCTURE_TIMEFRAME, TRADEABLE_MARKETS
from app.models import Indicator, KLine, Position, StateTransitionLog, StructureEvent, TradeSignal, TradingState
from app.services.risk import calculate_position_size, get_or_create_risk_config, portfolio_allows_new_position


def get_or_create_trading_state(session: Session, symbol: str) -> TradingState:
    record = session.scalar(select(TradingState).where(TradingState.symbol == symbol))
    if record is None:
        record = TradingState(symbol=symbol, state="IDLE", next_wait="等待市场和个股趋势过滤通过")
        session.add(record)
        session.commit()
        session.refresh(record)
    return record


def _transition(session: Session, record: TradingState, to_state: str, reason: str, next_wait: str = "") -> None:
    if record.state == to_state and record.last_reason == reason:
        record.next_wait = next_wait
        return
    session.add(StateTransitionLog(symbol=record.symbol, from_state=record.state, to_state=to_state, reason=reason))
    record.state = to_state
    record.last_reason = reason
    record.next_wait = next_wait


def _latest_event(session: Session, symbol: str, event_types: set[str]) -> StructureEvent | None:
    return session.scalar(
        select(StructureEvent)
        .where(
            StructureEvent.symbol == symbol,
            StructureEvent.timeframe == STRUCTURE_TIMEFRAME,
            StructureEvent.event_type.in_(event_types),
        )
        .order_by(StructureEvent.event_ts.desc())
        .limit(1)
    )


def _latest_bar_and_indicator(session: Session, symbol: str, timeframe: str) -> tuple[KLine, Indicator] | None:
    bar = session.scalar(
        select(KLine)
        .where(KLine.symbol == symbol, KLine.timeframe == timeframe, KLine.data_ok.is_(True))
        .order_by(KLine.ts.desc())
        .limit(1)
    )
    if not bar:
        return None
    indicator = session.scalar(
        select(Indicator).where(Indicator.symbol == symbol, Indicator.timeframe == timeframe, Indicator.ts == bar.ts)
    )
    if not indicator:
        return None
    return bar, indicator


def _recent_stop(session: Session, symbol: str) -> float | None:
    bars = list(
        session.scalars(
            select(KLine)
            .where(KLine.symbol == symbol, KLine.timeframe == DAILY, KLine.data_ok.is_(True))
            .order_by(KLine.ts.desc())
            .limit(10)
        )
    )
    latest = _latest_bar_and_indicator(session, symbol, DAILY)
    if len(bars) < 3 or latest is None:
        return None
    _, indicator = latest
    if indicator.atr is None:
        return None
    return min(bar.low for bar in bars) - indicator.atr * 0.5


def _entry_trigger(session: Session, symbol: str) -> tuple[bool, str]:
    latest = _latest_bar_and_indicator(session, symbol, DAILY)
    hourly = _latest_bar_and_indicator(session, symbol, HOUR_60)
    if latest is None or hourly is None:
        return False, "daily or 60m data missing"
    bar, indicator = latest
    hour_bar, hour_i = hourly
    if indicator.ma20 is None or indicator.volume_ma20 is None or indicator.macd_hist is None or indicator.macd_dif is None:
        return False, "daily indicators insufficient"
    previous = list(
        session.scalars(
            select(KLine)
            .where(KLine.symbol == symbol, KLine.timeframe == DAILY, KLine.ts < bar.ts, KLine.data_ok.is_(True))
            .order_by(KLine.ts.desc())
            .limit(8)
        )
    )
    if not previous:
        return False, "not enough prior bars for key high"
    key_high = max(item.high for item in previous)
    checks = [
        bar.close >= indicator.ma20,
        bar.close >= key_high * 0.995,
        indicator.macd_hist > 0,
        indicator.macd_dif >= 0 or (hour_i.macd_dif is not None and hour_i.macd_dif >= 0),
        bar.volume >= indicator.volume_ma20 * 0.65,
        hour_bar.close >= (hour_i.ma20 or hour_bar.close),
    ]
    if all(checks):
        return True, "price recovered MA20, broke recent key high, MACD improved, volume acceptable, 60m not weak"
    return False, "waiting for MA20 recovery, key high breakout, MACD improvement, volume confirmation, and 60m support"


def _signal_exists(session: Session, symbol: str, signal_type: str) -> bool:
    return (
        session.scalar(
            select(TradeSignal)
            .where(TradeSignal.symbol == symbol, TradeSignal.signal_type == signal_type, TradeSignal.status == "PENDING")
            .limit(1)
        )
        is not None
    )


def advance_state_machine(session: Session, symbol: str, market_state: str, stock_trend: str) -> TradingState:
    record = get_or_create_trading_state(session, symbol)
    today = date.today()
    if record.cooldown_until and record.cooldown_until >= today:
        _transition(session, record, "COOLDOWN", f"cooldown active until {record.cooldown_until}", "冷却期内只记录结构，不生成入场建议")
        session.commit()
        return record

    latest = _latest_bar_and_indicator(session, symbol, DAILY)
    if latest is None:
        _transition(session, record, "IDLE", "data missing or indicators unavailable", "等待有效行情和指标")
        session.commit()
        return record
    bar, indicator = latest
    position = session.scalar(select(Position).where(Position.symbol == symbol, Position.status == "OPEN"))
    if position:
        _manage_position(session, record, position, market_state)
        session.commit()
        return record

    if market_state not in TRADEABLE_MARKETS:
        _transition(session, record, "IDLE", f"market state {market_state} forbids new entries", "等待市场环境重新允许新开仓")
        session.commit()
        return record
    if stock_trend not in ENTRY_TRENDS:
        _transition(session, record, "IDLE", f"stock trend {stock_trend} is not eligible", "等待个股趋势恢复至 UPTREND 或 STRONG_UPTREND")
        session.commit()
        return record

    latest_structure = _latest_event(
        session,
        symbol,
        {"BOTTOM_PASSIVATION", "BOTTOM_STRUCTURE", "BOTTOM_FAILED", "TOP_STRUCTURE", "TOP_INVALIDATED"},
    )
    if latest_structure is None:
        _transition(session, record, "TREND_OK", "market and stock trend passed, no structure opportunity", "等待底钝化或可解释结构事件")
    elif latest_structure.event_type == "BOTTOM_PASSIVATION":
        _transition(session, record, "WATCH_BOTTOM", latest_structure.reason, "等待底结构确认，不能直接买入")
    elif latest_structure.event_type == "BOTTOM_FAILED":
        config = get_or_create_risk_config(session)
        record.cooldown_until = today + timedelta(days=config.cooldown_days)
        _transition(session, record, "COOLDOWN", latest_structure.reason, "底结构失败后进入冷却期")
    elif latest_structure.event_type == "BOTTOM_STRUCTURE":
        trigger, trigger_reason = _entry_trigger(session, symbol)
        if not trigger:
            _transition(session, record, "WAIT_ENTRY_TRIGGER", latest_structure.reason, trigger_reason)
        else:
            _create_entry_candidate(session, record, symbol, market_state, "SCRIPT_A_BOTTOM_TREND_RESUME", trigger_reason)
    elif latest_structure.event_type == "TOP_INVALIDATED" and stock_trend == "STRONG_UPTREND" and market_state in TRADEABLE_MARKETS:
        trigger, trigger_reason = _entry_trigger(session, symbol)
        if trigger:
            _create_entry_candidate(session, record, symbol, market_state, "SCRIPT_B_TOP_INVALIDATION_CONTINUATION", trigger_reason)
        else:
            _transition(session, record, "TREND_OK", latest_structure.reason, "顶结构失效后仍需趋势延续确认")
    else:
        _transition(session, record, "TREND_OK", latest_structure.reason, "等待底结构后的趋势恢复剧本")
    session.commit()
    return record


def _create_entry_candidate(session: Session, record: TradingState, symbol: str, market_state: str, script: str, reason: str) -> None:
    if _signal_exists(session, symbol, "ENTRY"):
        _transition(session, record, "ENTRY_CANDIDATE", "pending entry signal already exists", "等待人工审批或拒绝")
        return
    config = get_or_create_risk_config(session)
    allowed, portfolio_reason = portfolio_allows_new_position(session, symbol, config)
    if not allowed:
        _transition(session, record, "TREND_OK", portfolio_reason, "等待组合风险释放")
        return
    latest = _latest_bar_and_indicator(session, symbol, DAILY)
    if latest is None:
        _transition(session, record, "TREND_OK", "cannot create entry without latest price", "等待有效价格")
        return
    bar, _ = latest
    stop_price = _recent_stop(session, symbol)
    risk = calculate_position_size(config, bar.close, stop_price, market_state, script)
    if risk is None:
        _transition(session, record, "WAIT_ENTRY_TRIGGER", "risk calculation failed or stop unavailable", "无清晰止损位，不允许生成入场建议")
        return
    signal = TradeSignal(
        symbol=symbol,
        signal_type="ENTRY",
        script=script,
        action="入场候选",
        entry_price=risk.entry_price,
        stop_price=risk.stop_price,
        target_position_pct=risk.position_pct,
        shares=risk.shares,
        risk_amount=risk.allowed_loss,
        risk_r=1.0,
        reason=f"{reason}; stop={risk.stop_price:.2f}; shares={risk.shares}; generated by state machine, not score",
        score_display=_display_score(script, market_state),
    )
    session.add(signal)
    _transition(session, record, "ENTRY_CANDIDATE", signal.reason, "等待人工审批；批准后才进入模拟持仓")


def _manage_position(session: Session, record: TradingState, position: Position, market_state: str) -> None:
    latest = _latest_bar_and_indicator(session, position.symbol, DAILY)
    if latest is None:
        _transition(session, record, "IN_POSITION", "position held but latest data missing", "等待数据恢复，只允许人工风控")
        return
    bar, indicator = latest
    risk_per_share = position.entry_price - position.stop_price
    current_r = (bar.close - position.entry_price) / risk_per_share if risk_per_share > 0 else 0
    position.current_r = current_r
    if bar.close <= position.stop_price:
        _create_exit_signal(session, position, "硬止损触发，最高优先级清仓候选")
        _transition(session, record, "EXIT_CANDIDATE", "hard stop triggered", "等待人工确认模拟退出")
        return
    top_event = _latest_event(session, position.symbol, {"TOP_STRUCTURE"})
    if top_event and current_r > 0:
        _create_reduce_signal(session, position, f"持仓盈利 {current_r:.2f}R 且出现顶结构，生成风险减仓候选，不直接清仓")
        _transition(session, record, "RISK_PROTECTION", "top structure risk protection", "等待减仓审批或滑动止盈触发")
        return
    if indicator.ma60 is not None and bar.close < indicator.ma60:
        _create_exit_signal(session, position, "趋势破坏：收盘跌破 MA60，清仓候选")
        _transition(session, record, "EXIT_CANDIDATE", "trend break exit candidate", "等待人工确认模拟退出")
        return
    _update_trailing_stop(position, bar.close, indicator.atr, current_r, market_state)
    if position.trailing_stop and bar.close <= position.trailing_stop:
        _create_exit_signal(session, position, "滑动止盈触发，清仓候选")
        _transition(session, record, "EXIT_CANDIDATE", "trailing stop triggered", "等待人工确认模拟退出")
        return
    _transition(session, record, "IN_POSITION", f"position healthy at {current_r:.2f}R", "继续跟踪硬止损、顶结构、趋势破坏和滑动止盈")


def _update_trailing_stop(position: Position, close: float, atr: float | None, current_r: float, market_state: str) -> None:
    if atr is None or current_r < 1:
        return
    candidate = position.entry_price if current_r >= 1 else position.stop_price
    if current_r >= 2:
        candidate = max(candidate, close - atr * (2.0 if market_state == "RISK_ON" else 1.5))
    if position.trailing_stop is None:
        position.trailing_stop = max(position.stop_price, candidate)
    else:
        position.trailing_stop = max(position.trailing_stop, candidate)


def _create_reduce_signal(session: Session, position: Position, reason: str) -> None:
    if _signal_exists(session, position.symbol, "REDUCE"):
        return
    session.add(
        TradeSignal(
            symbol=position.symbol,
            signal_type="REDUCE",
            action="减仓候选",
            status="PENDING",
            entry_price=None,
            stop_price=position.trailing_stop or position.stop_price,
            shares=max(1, position.shares // 3),
            risk_amount=0,
            risk_r=position.current_r,
            reason=reason,
        )
    )


def _create_exit_signal(session: Session, position: Position, reason: str) -> None:
    if _signal_exists(session, position.symbol, "EXIT"):
        return
    session.add(
        TradeSignal(
            symbol=position.symbol,
            signal_type="EXIT",
            action="清仓候选",
            status="PENDING",
            stop_price=position.trailing_stop or position.stop_price,
            shares=position.shares,
            risk_amount=0,
            risk_r=position.current_r,
            reason=reason,
        )
    )


def _display_score(script: str, market_state: str) -> float:
    base = 70 if script == "SCRIPT_A_BOTTOM_TREND_RESUME" else 60
    if market_state == "RISK_ON":
        base += 10
    return float(base)
