from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable
from uuid import uuid4

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db import Base
from app.domain import CORE_TIMEFRAMES, DAILY, STRUCTURE_TIMEFRAME, TRIGGER_TIMEFRAME
from app.models import (
    BacktestTrade,
    Indicator,
    KLine,
    MarketState,
    Position,
    ReviewStat,
    RiskConfig,
    StockTrend,
    StructureEvent,
    TradeSignal,
    TradingState,
    WatchlistItem,
)
from app.services.approvals import approve_signal
from app.services.indicators import IndicatorRow, calculate_indicator_rows
from app.services.market import evaluate_market, persist_market_state
from app.services.risk import get_or_create_risk_config
from app.services.state_machine import advance_state_machine
from app.services.structures import detect_latest_structures, persist_structure_detections
from app.services.trend import evaluate_stock_trend, persist_stock_trend


StepObserver = Callable[[datetime, Session], None]


@dataclass
class ActiveReplayTrade:
    symbol: str
    signal_id: int
    position_id: int
    script: str
    source_structure_id: int | None
    structure_type: str
    structure_ts: datetime | None
    trigger_timeframe: str
    trigger_reason: str
    entry_ts: datetime
    entry_price: float
    stop_price: float
    shares: int
    risk_amount: float
    market_state: str
    stock_trend: str
    max_r: float = 0.0
    min_r: float = 0.0
    holding_bars: int = 0


def run_backtest(
    session: Session,
    settings: Settings,
    *,
    symbols: list[str] | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    step_observer: StepObserver | None = None,
) -> dict[str, object]:
    stock_symbols = symbols or _backtest_symbols(session, settings.market_symbols)
    source_symbols = list(dict.fromkeys([*settings.market_symbols, *stock_symbols]))
    source_bars = _source_bars(session, source_symbols, end)
    if not source_bars:
        return _empty_stats()
    indicator_rows = _precompute_indicators(source_bars)

    replay_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=replay_engine)
    replay_factory = sessionmaker(bind=replay_engine, autoflush=False, autocommit=False)
    run_id = uuid4().hex
    completed: list[BacktestTrade] = []

    with replay_factory() as replay:
        _seed_replay_metadata(session, replay, source_symbols)
        active: dict[str, ActiveReplayTrade] = {}
        bars_by_ts: dict[datetime, list[KLine]] = defaultdict(list)
        for bar in source_bars:
            bars_by_ts[_available_at(bar)].append(bar)

        for current_ts in sorted(bars_by_ts):
            copied = [_copy_bar(bar) for bar in bars_by_ts[current_ts]]
            affected = {(bar.symbol, bar.timeframe) for bar in copied}
            replay.add_all(copied)
            replay.add_all(
                [
                    _copy_indicator(bar, indicator_rows[(bar.symbol, bar.timeframe, bar.ts)])
                    for bar in bars_by_ts[current_ts]
                ]
            )
            replay.commit()

            market_eval = evaluate_market(replay, settings.market_symbols)
            persist_market_state(replay, market_eval)

            for symbol in stock_symbols:
                if (symbol, STRUCTURE_TIMEFRAME) not in affected:
                    continue
                trend_eval = evaluate_stock_trend(replay, symbol)
                detections = detect_latest_structures(replay, symbol, STRUCTURE_TIMEFRAME)
                persist_structure_detections(replay, detections, market_eval.state, trend_eval.trend)

            if step_observer:
                step_observer(current_ts, replay)

            decision_symbols = [
                symbol
                for symbol in stock_symbols
                if (symbol, TRIGGER_TIMEFRAME) in affected and (start is None or current_ts >= start)
            ]
            for symbol in decision_symbols:
                current_bar = replay.scalar(
                    select(KLine)
                    .where(KLine.symbol == symbol, KLine.timeframe == TRIGGER_TIMEFRAME)
                    .order_by(KLine.ts.desc())
                    .limit(1)
                )
                if current_bar is None:
                    continue

                if symbol in active:
                    closed = _apply_bar_risk(replay, active[symbol], current_bar, current_bar.ts)
                    if closed:
                        completed.append(closed)
                        del active[symbol]
                        continue

                trend_eval = evaluate_stock_trend(replay, symbol)
                persist_stock_trend(replay, trend_eval)
                advance_state_machine(
                    replay,
                    symbol,
                    market_eval.state,
                    trend_eval.trend,
                    as_of_date=current_bar.ts.date(),
                )

                if symbol in active:
                    exit_signal = replay.scalar(
                        select(TradeSignal)
                        .where(
                            TradeSignal.symbol == symbol,
                            TradeSignal.signal_type == "EXIT",
                            TradeSignal.status == "PENDING",
                        )
                        .order_by(TradeSignal.created_at.desc())
                        .limit(1)
                    )
                    if exit_signal:
                        exit_reason = exit_signal.reason
                        approve_signal(replay, exit_signal.id)
                        closed = _finish_trade(active[symbol], current_bar.ts, current_bar.close, exit_reason)
                        completed.append(closed)
                        del active[symbol]
                        _set_replay_cooldown(replay, symbol, current_bar.ts.date())
                    continue

                entry_signal = replay.scalar(
                    select(TradeSignal)
                    .where(
                        TradeSignal.symbol == symbol,
                        TradeSignal.signal_type == "ENTRY",
                        TradeSignal.status == "PENDING",
                    )
                    .order_by(TradeSignal.created_at.desc())
                    .limit(1)
                )
                if entry_signal is None:
                    continue
                approve_signal(replay, entry_signal.id, note="回测规则：有效信号当根自动批准")
                position = replay.scalar(
                    select(Position).where(Position.symbol == symbol, Position.status == "OPEN")
                )
                if position is None or entry_signal.entry_price is None or entry_signal.stop_price is None:
                    continue
                structure = replay.get(StructureEvent, entry_signal.source_structure_id)
                active[symbol] = ActiveReplayTrade(
                    symbol=symbol,
                    signal_id=entry_signal.id,
                    position_id=position.id,
                    script=entry_signal.script,
                    source_structure_id=entry_signal.source_structure_id,
                    structure_type=structure.event_type if structure else "",
                    structure_ts=structure.event_ts if structure else None,
                    trigger_timeframe=entry_signal.trigger_timeframe or "",
                    trigger_reason=entry_signal.reason,
                    entry_ts=entry_signal.trigger_ts or current_bar.ts,
                    entry_price=entry_signal.entry_price,
                    stop_price=entry_signal.stop_price,
                    shares=entry_signal.shares or 0,
                    risk_amount=entry_signal.risk_amount or 0,
                    market_state=market_eval.state,
                    stock_trend=trend_eval.trend,
                )

        for symbol, trade in list(active.items()):
            last_bar = replay.scalar(
                select(KLine)
                .where(KLine.symbol == symbol, KLine.timeframe == TRIGGER_TIMEFRAME)
                .order_by(KLine.ts.desc())
                .limit(1)
            )
            if last_bar:
                completed.append(_finish_trade(trade, last_bar.ts, last_bar.close, "END_OF_BACKTEST"))
        replay_entry_signals = list(
            replay.scalars(select(TradeSignal).where(TradeSignal.signal_type == "ENTRY"))
        )
        replay_bottom_structures = list(
            replay.scalars(
                select(StructureEvent).where(StructureEvent.event_type == "BOTTOM_STRUCTURE")
            )
        )

    for trade in completed:
        trade.run_id = run_id
        session.add(trade)
    session.flush()
    trade_ids = [trade.id for trade in completed]
    stats = _calculate_stats(
        completed,
        source_bars,
        stock_symbols,
        entry_signals=replay_entry_signals,
        bottom_structures=replay_bottom_structures,
    )
    _persist_stats(session, stats)
    session.commit()
    return {"run_id": run_id, "trade_ids": trade_ids, **stats}


def _apply_bar_risk(
    replay: Session,
    trade: ActiveReplayTrade,
    bar: KLine,
    current_ts: datetime,
) -> BacktestTrade | None:
    risk_per_share = trade.entry_price - trade.stop_price
    if risk_per_share <= 0:
        return _finish_trade(trade, current_ts, bar.close, "INVALID_RISK")
    trade.holding_bars += 1
    trade.max_r = max(trade.max_r, (bar.high - trade.entry_price) / risk_per_share)
    trade.min_r = min(trade.min_r, (bar.low - trade.entry_price) / risk_per_share)
    if bar.low <= trade.stop_price:
        position = replay.get(Position, trade.position_id)
        if position:
            position.status = "CLOSED"
            position.exit_reason = "HARD_STOP"
        replay.commit()
        return _finish_trade(trade, current_ts, trade.stop_price, "HARD_STOP")
    return None


def _finish_trade(
    trade: ActiveReplayTrade,
    exit_ts: datetime,
    exit_price: float,
    exit_reason: str,
) -> BacktestTrade:
    risk_per_share = trade.entry_price - trade.stop_price
    final_r = (exit_price - trade.entry_price) / risk_per_share if risk_per_share > 0 else 0.0
    return BacktestTrade(
        run_id="",
        symbol=trade.symbol,
        script=trade.script,
        source_structure_id=trade.source_structure_id,
        structure_type=trade.structure_type,
        structure_ts=trade.structure_ts,
        trigger_timeframe=trade.trigger_timeframe,
        trigger_reason=trade.trigger_reason,
        entry_ts=trade.entry_ts,
        entry_price=trade.entry_price,
        stop_price=trade.stop_price,
        shares=trade.shares,
        risk_amount=trade.risk_amount,
        exit_ts=exit_ts,
        exit_price=exit_price,
        exit_reason=exit_reason,
        max_r=trade.max_r,
        min_r=trade.min_r,
        final_r=final_r,
        holding_bars=trade.holding_bars,
        market_state_at_entry=trade.market_state,
        stock_trend_at_entry=trade.stock_trend,
    )


def _calculate_stats(
    trades: list[BacktestTrade],
    source_bars: list[KLine],
    symbols: list[str],
    *,
    entry_signals: list[TradeSignal] | None = None,
    bottom_structures: list[StructureEvent] | None = None,
) -> dict[str, object]:
    final_rs = [trade.final_r for trade in trades]
    wins = [value for value in final_rs if value > 0]
    losses = [value for value in final_rs if value <= 0]
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    consecutive_losses = 0
    max_consecutive_losses = 0
    for value in final_rs:
        equity += value
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity - peak)
        consecutive_losses = consecutive_losses + 1 if value <= 0 else 0
        max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)

    yearly: dict[str, float] = defaultdict(float)
    market_groups: dict[str, list[float]] = defaultdict(list)
    scripts: dict[str, list[float]] = defaultdict(list)
    for trade in trades:
        yearly[str(trade.exit_ts.year)] += trade.final_r
        market_groups[trade.market_state_at_entry].append(trade.final_r)
        scripts[trade.script].append(trade.final_r)

    signal_records = entry_signals or []
    trigger_failures = sum(1 for signal in signal_records if signal.status == "CANCELLED_BY_TRIGGER")
    expired = sum(1 for signal in signal_records if signal.status == "EXPIRED")
    structures = bottom_structures or []
    successful_structures = sum(1 for structure in structures if structure.triggered_entry)
    decision_bars = sum(1 for bar in source_bars if bar.symbol in symbols and bar.timeframe == TRIGGER_TIMEFRAME)
    holding_bars = sum(trade.holding_bars for trade in trades)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "trade_count": len(trades),
        "win_rate": len(wins) / len(trades) if trades else 0.0,
        "avg_r": sum(final_rs) / len(final_rs) if final_rs else 0.0,
        "median_r": _median(final_rs),
        "max_drawdown": max_drawdown,
        "max_consecutive_losses": max_consecutive_losses,
        "avg_holding_period": holding_bars / len(trades) if trades else 0.0,
        "profit_factor": gross_profit / gross_loss if gross_loss else (gross_profit if gross_profit else 0.0),
        "exposure": holding_bars / decision_bars if decision_bars else 0.0,
        "yearly_performance": dict(yearly),
        "market_state_group_performance": {
            key: sum(values) / len(values) for key, values in market_groups.items()
        },
        "script_a_performance": _script_average(scripts, "SCRIPT_A_BOTTOM_TREND_RESUME"),
        "script_b_performance": _script_average(scripts, "SCRIPT_B_TOP_INVALIDATION_CONTINUATION"),
        "structure_success_rate": successful_structures / len(structures) if structures else 0.0,
        "signal_expiry_rate": expired / len(signal_records) if signal_records else 0.0,
        "trigger_failure_rate": trigger_failures / len(signal_records) if signal_records else 0.0,
    }


def _persist_stats(session: Session, stats: dict[str, object]) -> None:
    session.execute(delete(ReviewStat).where(ReviewStat.subject_type == "BACKTEST_SYSTEM"))
    for metric, value in stats.items():
        if isinstance(value, (int, float)):
            session.add(
                ReviewStat(
                    subject_type="BACKTEST_SYSTEM",
                    subject_id=0,
                    metric=metric,
                    value=float(value),
                )
            )
        elif isinstance(value, dict):
            for group, group_value in value.items():
                session.add(
                    ReviewStat(
                        subject_type="BACKTEST_SYSTEM",
                        subject_id=0,
                        metric=f"{metric}:{group}",
                        value=float(group_value),
                    )
                )


def _source_bars(session: Session, symbols: list[str], end: datetime | None) -> list[KLine]:
    statement = (
        select(KLine)
        .where(
            KLine.symbol.in_(symbols),
            KLine.timeframe.in_((*CORE_TIMEFRAMES, TRIGGER_TIMEFRAME)),
            KLine.data_ok.is_(True),
        )
        .order_by(KLine.ts.asc(), KLine.symbol.asc(), KLine.timeframe.asc())
    )
    if end is not None:
        statement = statement.where(KLine.ts <= end)
    return list(session.scalars(statement))


def _backtest_symbols(session: Session, market_symbols: list[str]) -> list[str]:
    items = list(
        session.scalars(
            select(WatchlistItem.symbol).where(
                WatchlistItem.active.is_(True),
                WatchlistItem.symbol.not_in(market_symbols),
            )
        )
    )
    if items:
        return items
    return list(
        session.scalars(
            select(KLine.symbol)
            .where(KLine.symbol.not_in(market_symbols))
            .distinct()
            .order_by(KLine.symbol)
        )
    )


def _seed_replay_metadata(source: Session, replay: Session, symbols: list[str]) -> None:
    source_config = source.scalar(select(RiskConfig).order_by(RiskConfig.id.asc()).limit(1))
    config = get_or_create_risk_config(replay)
    if source_config:
        for field in (
            "account_equity",
            "risk_per_trade_pct",
            "neutral_risk_multiplier",
            "script_b_risk_multiplier",
            "max_positions",
            "max_symbol_position_pct",
            "max_industry_exposure_pct",
            "cooldown_days",
        ):
            setattr(config, field, getattr(source_config, field))
    for symbol in symbols:
        source_item = source.scalar(select(WatchlistItem).where(WatchlistItem.symbol == symbol))
        replay.add(
            WatchlistItem(
                symbol=symbol,
                name=source_item.name if source_item else "",
                industry=source_item.industry if source_item else "",
                source_group="BACKTEST",
                active=True,
            )
        )
    replay.commit()


def _copy_bar(bar: KLine) -> KLine:
    return KLine(
        symbol=bar.symbol,
        timeframe=bar.timeframe,
        ts=bar.ts,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
        data_ok=bar.data_ok,
        anomaly_reason=bar.anomaly_reason,
    )


def _copy_indicator(bar: KLine, row: IndicatorRow) -> Indicator:
    return Indicator(
        symbol=bar.symbol,
        timeframe=bar.timeframe,
        ts=bar.ts,
        ma20=row.ma20,
        ma60=row.ma60,
        macd_dif=row.macd_dif,
        macd_dea=row.macd_dea,
        macd_hist=row.macd_hist,
        atr=row.atr,
        volume_ma20=row.volume_ma20,
    )


def _precompute_indicators(source_bars: list[KLine]) -> dict[tuple[str, str, datetime], IndicatorRow]:
    grouped: dict[tuple[str, str], list[KLine]] = defaultdict(list)
    for bar in source_bars:
        grouped[(bar.symbol, bar.timeframe)].append(bar)
    output: dict[tuple[str, str, datetime], IndicatorRow] = {}
    for (symbol, timeframe), bars in grouped.items():
        ordered = sorted(bars, key=lambda item: item.ts)
        rows = calculate_indicator_rows(ordered)
        for bar, row in zip(ordered, rows, strict=True):
            output[(symbol, timeframe, bar.ts)] = row
    return output


def _available_at(bar: KLine) -> datetime:
    if bar.timeframe == DAILY:
        return bar.ts + timedelta(days=1)
    if bar.timeframe == STRUCTURE_TIMEFRAME:
        return bar.ts + timedelta(hours=1)
    if bar.timeframe == TRIGGER_TIMEFRAME:
        return bar.ts + timedelta(minutes=15)
    return bar.ts


def _set_replay_cooldown(replay: Session, symbol: str, as_of: date) -> None:
    state = replay.scalar(select(TradingState).where(TradingState.symbol == symbol))
    config = get_or_create_risk_config(replay)
    if state:
        state.state = "COOLDOWN"
        state.cooldown_until = as_of + timedelta(days=config.cooldown_days)
    replay.commit()


def _script_average(groups: dict[str, list[float]], script: str) -> float:
    values = groups.get(script, [])
    return sum(values) / len(values) if values else 0.0


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _empty_stats() -> dict[str, object]:
    return {
        "run_id": "",
        "trade_ids": [],
        "trade_count": 0,
        "win_rate": 0.0,
        "avg_r": 0.0,
        "median_r": 0.0,
        "max_drawdown": 0.0,
        "max_consecutive_losses": 0,
        "avg_holding_period": 0.0,
        "profit_factor": 0.0,
        "exposure": 0.0,
        "yearly_performance": {},
        "market_state_group_performance": {},
        "script_a_performance": 0.0,
        "script_b_performance": 0.0,
        "structure_success_rate": 0.0,
        "signal_expiry_rate": 0.0,
        "trigger_failure_rate": 0.0,
    }
