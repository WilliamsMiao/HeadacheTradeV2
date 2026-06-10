from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import TRADEABLE_MARKETS, TRIGGER_TIMEFRAME
from app.models import Indicator, KLine, StructureEvent, TradeSignal
from app.strategy_config import CORRECTION_CONFIG, CorrectionConfig


@dataclass(frozen=True)
class CorrectionResult:
    status: str
    reason: str
    target_state: str
    start_cooldown: bool = False


def reconcile_pending_entry(
    session: Session,
    symbol: str,
    market_state: str,
    config: CorrectionConfig = CORRECTION_CONFIG,
) -> CorrectionResult | None:
    signal = session.scalar(
        select(TradeSignal)
        .where(
            TradeSignal.symbol == symbol,
            TradeSignal.signal_type == "ENTRY",
            TradeSignal.status == "PENDING",
        )
        .order_by(TradeSignal.created_at.desc())
        .limit(1)
    )
    if signal is None:
        return None

    structure = session.get(StructureEvent, signal.source_structure_id) if signal.source_structure_id else None
    structure_failure = _structure_failure(session, structure)
    if structure_failure:
        return _cancel(
            signal,
            "CANCELLED_BY_STRUCTURE",
            structure_failure,
            "COOLDOWN",
            start_cooldown=True,
        )

    trigger_failure = entry_trigger_failure_reason(session, signal, config)
    if trigger_failure:
        return _cancel(signal, "CANCELLED_BY_TRIGGER", trigger_failure, "WAIT_15M_TRIGGER")

    bars_after_trigger = _bars_after_trigger(session, signal)
    if len(bars_after_trigger) >= config.signal_expiry_bars:
        return _cancel(
            signal,
            "EXPIRED",
            f"入场建议超过 {config.signal_expiry_bars} 根 15 分钟 K 线仍未审批",
            "WAIT_15M_TRIGGER",
        )

    if market_state not in TRADEABLE_MARKETS:
        market_label = {
            "NEUTRAL_NEGATIVE": "中性偏弱",
            "RISK_OFF": "风险关闭",
        }.get(market_state, "不允许新开仓")
        return _cancel(
            signal,
            "CANCELLED_BY_MARKET",
            f"市场状态已降级为“{market_label}”，不再允许新开仓",
            "IDLE",
        )
    return None


def entry_trigger_failure_reason(
    session: Session,
    signal: TradeSignal,
    config: CorrectionConfig = CORRECTION_CONFIG,
) -> str | None:
    if signal.trigger_ts is None or signal.trigger_level is None or signal.entry_price is None:
        return None
    bars = _bars_after_trigger(session, signal)[: config.trigger_failure_bars]
    if not bars:
        return None

    previous_hist = session.scalar(
        select(Indicator.macd_hist).where(
            Indicator.symbol == signal.symbol,
            Indicator.timeframe == TRIGGER_TIMEFRAME,
            Indicator.ts == signal.trigger_ts,
        )
    )
    for bar in bars:
        indicator = session.scalar(
            select(Indicator).where(
                Indicator.symbol == signal.symbol,
                Indicator.timeframe == TRIGGER_TIMEFRAME,
                Indicator.ts == bar.ts,
            )
        )
        if bar.close < signal.trigger_level:
            return f"15 分钟触发后于 {bar.ts:%Y-%m-%d %H:%M} 跌回触发位 {signal.trigger_level:.2f} 下方"
        if indicator and indicator.ma20 is not None and bar.close < indicator.ma20:
            return f"15 分钟触发后于 {bar.ts:%Y-%m-%d %H:%M} 跌回 MA20 下方"
        if (
            indicator
            and indicator.macd_hist is not None
            and previous_hist is not None
            and indicator.macd_hist < previous_hist
        ):
            return f"15 分钟触发后于 {bar.ts:%Y-%m-%d %H:%M} MACD 柱重新转弱"
        if indicator and indicator.macd_hist is not None:
            previous_hist = indicator.macd_hist

    latest = bars[-1]
    deviation = abs(latest.close - signal.entry_price) / signal.entry_price
    if deviation > config.maximum_entry_deviation_pct:
        return (
            f"当前价格偏离建议入场价 {deviation:.1%}，"
            f"超过 {config.maximum_entry_deviation_pct:.1%} 限制"
        )
    return None


def _bars_after_trigger(session: Session, signal: TradeSignal) -> list[KLine]:
    if signal.trigger_ts is None:
        return []
    return list(
        session.scalars(
            select(KLine)
            .where(
                KLine.symbol == signal.symbol,
                KLine.timeframe == TRIGGER_TIMEFRAME,
                KLine.ts > signal.trigger_ts,
                KLine.data_ok.is_(True),
            )
            .order_by(KLine.ts.asc())
        )
    )


def _structure_failure(session: Session, structure: StructureEvent | None) -> str | None:
    if structure is None:
        return "来源 60 分钟底结构不存在"
    if structure.invalidated or structure.became_failed:
        return "来源 60 分钟底结构已经失败或失效"
    failure = session.scalar(
        select(StructureEvent)
        .where(
            StructureEvent.event_type == "BOTTOM_FAILED",
            StructureEvent.parent_event_id == structure.id,
        )
        .order_by(StructureEvent.event_ts.desc())
        .limit(1)
    )
    if failure:
        return f"来源 60 分钟底结构已在 {failure.event_ts:%Y-%m-%d %H:%M} 确认失败"
    return None


def _cancel(
    signal: TradeSignal,
    status: str,
    reason: str,
    target_state: str,
    *,
    start_cooldown: bool = False,
) -> CorrectionResult:
    signal.status = status
    signal.cancel_reason = reason
    return CorrectionResult(status, reason, target_state, start_cooldown)
