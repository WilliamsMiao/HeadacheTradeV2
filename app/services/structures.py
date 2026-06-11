from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Indicator, KLine, StructureEvent
from app.strategy_config import STRUCTURE_CONFIG, StructureConfig


@dataclass(frozen=True)
class StructureDetection:
    symbol: str
    timeframe: str
    event_type: str
    event_ts: datetime
    price: float
    reason: str
    pivot_low: float | None = None
    pivot_high: float | None = None
    confirm_level: float | None = None
    invalidation_level: float | None = None
    trigger_level: float | None = None
    parent_event_type: str | None = None
    parent_event_ts: datetime | None = None
    expires_at: datetime | None = None
    script_version: str = STRUCTURE_CONFIG.script_version


def _joined_series(session: Session, symbol: str, timeframe: str, limit: int = 160) -> list[tuple[KLine, Indicator]]:
    klines = list(
        session.scalars(
            select(KLine)
            .where(KLine.symbol == symbol, KLine.timeframe == timeframe, KLine.data_ok.is_(True))
            .order_by(KLine.ts.desc())
            .limit(limit)
        )
    )
    output: list[tuple[KLine, Indicator]] = []
    for kline in reversed(klines):
        indicator = session.scalar(
            select(Indicator).where(
                Indicator.symbol == symbol,
                Indicator.timeframe == timeframe,
                Indicator.ts == kline.ts,
            )
        )
        if indicator and indicator.macd_dif is not None and indicator.macd_hist is not None:
            output.append((kline, indicator))
    return output


def detect_latest_structures(
    session: Session,
    symbol: str,
    timeframe: str,
    config: StructureConfig = STRUCTURE_CONFIG,
) -> list[StructureDetection]:
    series = _joined_series(session, symbol, timeframe)
    if len(series) < config.minimum_history_bars:
        return []

    detections: list[StructureDetection] = []
    bottom_passivation: StructureDetection | None = None
    bottom_structure: StructureDetection | None = None
    top_passivation: StructureDetection | None = None
    top_structure: StructureDetection | None = None

    for index in range(config.lookback_bars + 5, len(series)):
        found = _detect_at_index(
            series,
            index,
            bottom_passivation,
            bottom_structure,
            top_passivation,
            top_structure,
            config,
        )
        for detection in found:
            detections.append(detection)
            if detection.event_type == "BOTTOM_PASSIVATION":
                bottom_passivation = detection
            elif detection.event_type == "BOTTOM_STRUCTURE":
                bottom_structure = detection
            elif detection.event_type == "BOTTOM_FAILED":
                bottom_passivation = None
                bottom_structure = None
            elif detection.event_type == "TOP_PASSIVATION":
                top_passivation = detection
            elif detection.event_type == "TOP_STRUCTURE":
                top_structure = detection
            elif detection.event_type == "TOP_INVALIDATED":
                top_passivation = None
                top_structure = None
    return detections


def _detect_at_index(
    series: list[tuple[KLine, Indicator]],
    index: int,
    bottom_passivation: StructureDetection | None,
    bottom_structure: StructureDetection | None,
    top_passivation: StructureDetection | None,
    top_structure: StructureDetection | None,
    config: StructureConfig = STRUCTURE_CONFIG,
) -> list[StructureDetection]:
    detections: list[StructureDetection] = []
    current_bar, current_i = series[index]
    _, previous_i = series[index - 1]
    lookback = series[max(0, index - config.lookback_bars) : index]
    recent = series[max(0, index - config.confirmation_bars) : index]
    lows = [item[0].low for item in lookback]
    highs = [item[0].high for item in lookback]
    difs = [item[1].macd_dif for item in lookback if item[1].macd_dif is not None]
    if not lows or not highs or not difs or previous_i.macd_hist is None:
        return []

    hist_improving = current_i.macd_hist > previous_i.macd_hist
    hist_weakening = current_i.macd_hist < previous_i.macd_hist
    expiry = current_bar.ts + timedelta(days=config.structure_expiry_days)

    near_low = current_bar.low <= min(lows) * config.near_low_ratio
    dif_higher_low = current_i.macd_dif > min(difs)
    if bottom_passivation is None and bottom_structure is None and near_low and dif_higher_low and hist_improving:
        pivot_low = min(current_bar.low, min(lows))
        bottom_passivation_detection = StructureDetection(
            symbol=current_bar.symbol,
            timeframe=current_bar.timeframe,
            event_type="BOTTOM_PASSIVATION",
            event_ts=current_bar.ts,
            price=current_bar.close,
            pivot_low=pivot_low,
            invalidation_level=pivot_low,
            expires_at=expiry,
            reason=(
                f"price near stage low {pivot_low:.2f} while MACD DIF holds a higher low "
                "and histogram improves"
            ),
        )
        detections.append(bottom_passivation_detection)
        bottom_passivation = bottom_passivation_detection

    near_high = current_bar.high >= max(highs) * config.near_high_ratio
    dif_lower_high = current_i.macd_dif < max(difs)
    if top_passivation is None and top_structure is None and near_high and dif_lower_high and hist_weakening:
        pivot_high = max(current_bar.high, max(highs))
        top_passivation_detection = StructureDetection(
            symbol=current_bar.symbol,
            timeframe=current_bar.timeframe,
            event_type="TOP_PASSIVATION",
            event_ts=current_bar.ts,
            price=current_bar.close,
            pivot_high=pivot_high,
            invalidation_level=pivot_high,
            expires_at=expiry,
            reason=(
                f"price near stage high {pivot_high:.2f} while MACD DIF fails to confirm "
                "and histogram weakens"
            ),
        )
        detections.append(top_passivation_detection)
        top_passivation = top_passivation_detection

    if bottom_structure is None and bottom_passivation and bottom_passivation.event_ts < current_bar.ts:
        key_high = max(item[0].high for item in recent)
        ma20_ok = current_i.ma20 is not None and current_bar.close >= current_i.ma20
        volume_ok = current_i.volume_ma20 is None or current_bar.volume >= current_i.volume_ma20 * config.minimum_volume_ratio
        dif_turning = current_i.macd_dif >= previous_i.macd_dif
        if current_bar.close >= key_high and ma20_ok and hist_improving and dif_turning and volume_ok:
            pivot_low = bottom_passivation.pivot_low
            detections.append(
                StructureDetection(
                    symbol=current_bar.symbol,
                    timeframe=current_bar.timeframe,
                    event_type="BOTTOM_STRUCTURE",
                    event_ts=current_bar.ts,
                    price=current_bar.close,
                    pivot_low=pivot_low,
                    confirm_level=key_high,
                    invalidation_level=pivot_low,
                    trigger_level=key_high,
                    parent_event_type="BOTTOM_PASSIVATION",
                    parent_event_ts=bottom_passivation.event_ts,
                    expires_at=expiry,
                    reason=(
                        f"bottom passivation confirmed above {key_high:.2f}; pivot low {pivot_low:.2f}; "
                        "MA20 recovered, MACD improved, and volume accepted"
                    ),
                )
            )

    if top_structure is None and top_passivation and top_passivation.event_ts < current_bar.ts:
        key_low = min(item[0].low for item in recent)
        dif_down = current_i.macd_dif <= previous_i.macd_dif
        if current_bar.close <= key_low and hist_weakening and dif_down:
            pivot_high = top_passivation.pivot_high
            detections.append(
                StructureDetection(
                    symbol=current_bar.symbol,
                    timeframe=current_bar.timeframe,
                    event_type="TOP_STRUCTURE",
                    event_ts=current_bar.ts,
                    price=current_bar.close,
                    pivot_high=pivot_high,
                    confirm_level=key_low,
                    invalidation_level=pivot_high,
                    trigger_level=key_low,
                    parent_event_type="TOP_PASSIVATION",
                    parent_event_ts=top_passivation.event_ts,
                    expires_at=expiry,
                    reason=(
                        f"top passivation confirmed below {key_low:.2f}; pivot high {pivot_high:.2f}; "
                        "MACD weakening continued"
                    ),
                )
            )

    if bottom_structure and bottom_structure.event_ts < current_bar.ts:
        invalidation_level = bottom_structure.invalidation_level
        if invalidation_level is not None and current_bar.close < invalidation_level and hist_weakening:
            detections.append(
                StructureDetection(
                    symbol=current_bar.symbol,
                    timeframe=current_bar.timeframe,
                    event_type="BOTTOM_FAILED",
                    event_ts=current_bar.ts,
                    price=current_bar.close,
                    pivot_low=bottom_structure.pivot_low,
                    confirm_level=bottom_structure.confirm_level,
                    invalidation_level=invalidation_level,
                    parent_event_type="BOTTOM_STRUCTURE",
                    parent_event_ts=bottom_structure.event_ts,
                    reason=(
                        f"bottom structure failed below invalidation {invalidation_level:.2f} "
                        "with renewed MACD histogram deterioration"
                    ),
                )
            )

    if top_structure and top_structure.event_ts < current_bar.ts:
        invalidation_level = top_structure.invalidation_level
        if (
            invalidation_level is not None
            and current_bar.close > invalidation_level
            and current_i.ma20 is not None
            and current_bar.close > current_i.ma20
        ):
            detections.append(
                StructureDetection(
                    symbol=current_bar.symbol,
                    timeframe=current_bar.timeframe,
                    event_type="TOP_INVALIDATED",
                    event_ts=current_bar.ts,
                    price=current_bar.close,
                    pivot_high=top_structure.pivot_high,
                    confirm_level=top_structure.confirm_level,
                    invalidation_level=invalidation_level,
                    parent_event_type="TOP_STRUCTURE",
                    parent_event_ts=top_structure.event_ts,
                    reason=(
                        f"top structure invalidated above {invalidation_level:.2f} "
                        "while price held above MA20"
                    ),
                )
            )
    return detections


def _parent_event(session: Session, detection: StructureDetection) -> StructureEvent | None:
    if detection.parent_event_type is None or detection.parent_event_ts is None:
        return None
    return session.scalar(
        select(StructureEvent).where(
            StructureEvent.symbol == detection.symbol,
            StructureEvent.timeframe == detection.timeframe,
            StructureEvent.event_type == detection.parent_event_type,
            StructureEvent.event_ts == detection.parent_event_ts,
        )
    )


def persist_structure_detections(
    session: Session,
    detections: list[StructureDetection],
    market_state: str,
    stock_trend: str,
) -> list[StructureEvent]:
    records: list[StructureEvent] = []
    for detection in detections:
        existing = session.scalar(
            select(StructureEvent).where(
                StructureEvent.symbol == detection.symbol,
                StructureEvent.timeframe == detection.timeframe,
                StructureEvent.event_type == detection.event_type,
                StructureEvent.event_ts == detection.event_ts,
            )
        )
        if existing:
            existing.direction = _event_direction(detection.event_type, stock_trend)
            existing.stage = _event_stage(detection.event_type)
            existing.suggested_action = _event_action(detection.event_type, stock_trend)
            records.append(existing)
            continue

        parent = _parent_event(session, detection)
        event = StructureEvent(
            symbol=detection.symbol,
            timeframe=detection.timeframe,
            event_type=detection.event_type,
            event_ts=detection.event_ts,
            price=detection.price,
            reason=detection.reason,
            pivot_low=detection.pivot_low,
            pivot_high=detection.pivot_high,
            confirm_level=detection.confirm_level,
            invalidation_level=detection.invalidation_level,
            trigger_level=detection.trigger_level,
            parent_event_id=parent.id if parent else None,
            expires_at=detection.expires_at,
            script_version=detection.script_version,
            market_state=market_state,
            stock_trend=stock_trend,
            direction=_event_direction(detection.event_type, stock_trend),
            stage=_event_stage(detection.event_type),
            suggested_action=_event_action(detection.event_type, stock_trend),
        )
        session.add(event)
        session.flush()
        if parent and detection.event_type == "BOTTOM_FAILED":
            parent.became_failed = True
            parent.invalidated = True
        elif parent and detection.event_type == "TOP_INVALIDATED":
            parent.invalidated = True
        records.append(event)
    session.commit()
    return records


def update_structure_follow_through(session: Session) -> int:
    events = list(session.scalars(select(StructureEvent).where(StructureEvent.follow_5_return.is_(None))))
    updated = 0
    for event in events:
        bars = list(
            session.scalars(
                select(KLine)
                .where(
                    KLine.symbol == event.symbol,
                    KLine.timeframe == event.timeframe,
                    KLine.ts > event.event_ts,
                    KLine.data_ok.is_(True),
                )
                .order_by(KLine.ts)
                .limit(20)
            )
        )
        if len(bars) >= 5:
            event.follow_5_return = bars[4].close / event.price - 1
        if len(bars) >= 10:
            event.follow_10_return = bars[9].close / event.price - 1
        if len(bars) >= 20:
            event.follow_20_return = bars[19].close / event.price - 1
        if bars:
            event.max_up_return = max(bar.high for bar in bars) / event.price - 1
            event.max_down_return = min(bar.low for bar in bars) / event.price - 1
        updated += 1
    session.commit()
    return updated


def _event_direction(event_type: str, daily_state: str) -> str:
    if event_type in {"BOTTOM_PASSIVATION", "BOTTOM_STRUCTURE", "TOP_INVALIDATED"}:
        return "LONG"
    if event_type == "TOP_STRUCTURE" and daily_state in {"DAILY_WEAK_BEAR", "DAILY_STRONG_BEAR"}:
        return "SHORT"
    return "RISK"


def _event_stage(event_type: str) -> str:
    if event_type.endswith("PASSIVATION"):
        return "PASSIVATION"
    if event_type in {"BOTTOM_STRUCTURE", "TOP_STRUCTURE"}:
        return "CONFIRMED"
    if event_type.endswith("FAILED"):
        return "FAILED"
    if event_type.endswith("INVALIDATED"):
        return "INVALIDATED"
    return "UNKNOWN"


def _event_action(event_type: str, daily_state: str) -> str:
    if event_type == "BOTTOM_STRUCTURE":
        return "生成多头计划并等待关键价位"
    if event_type == "TOP_STRUCTURE" and daily_state in {"DAILY_WEAK_BEAR", "DAILY_STRONG_BEAR"}:
        return "评估下行计划，不直接做空"
    if event_type == "TOP_STRUCTURE":
        return "进入风险保护观察，不直接清仓"
    if event_type == "TOP_INVALIDATED":
        return "评估强趋势恢复计划"
    return "继续观察，等待结构确认"
