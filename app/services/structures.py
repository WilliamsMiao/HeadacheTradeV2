from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Indicator, KLine, StructureEvent


@dataclass(frozen=True)
class StructureDetection:
    symbol: str
    timeframe: str
    event_type: str
    event_ts: object
    price: float
    reason: str


def _joined_series(session: Session, symbol: str, timeframe: str, limit: int = 120) -> list[tuple[KLine, Indicator]]:
    klines = list(
        session.scalars(
            select(KLine)
            .where(KLine.symbol == symbol, KLine.timeframe == timeframe, KLine.data_ok.is_(True))
            .order_by(KLine.ts.desc())
            .limit(limit)
        )
    )
    klines = list(reversed(klines))
    output: list[tuple[KLine, Indicator]] = []
    for kline in klines:
        indicator = session.scalar(
            select(Indicator).where(Indicator.symbol == symbol, Indicator.timeframe == timeframe, Indicator.ts == kline.ts)
        )
        if indicator and indicator.macd_dif is not None and indicator.macd_hist is not None:
            output.append((kline, indicator))
    return output


def detect_latest_structures(session: Session, symbol: str, timeframe: str) -> list[StructureDetection]:
    series = _joined_series(session, symbol, timeframe)
    if len(series) < 40:
        return []
    detections: list[StructureDetection] = []
    bottom_passivation: StructureDetection | None = None
    bottom_structure: StructureDetection | None = None
    top_passivation: StructureDetection | None = None
    top_structure: StructureDetection | None = None
    for index in range(35, len(series)):
        detections_for_index = _detect_at_index(series, index, bottom_passivation, bottom_structure, top_passivation, top_structure)
        for detection in detections_for_index:
            detections.append(detection)
            if detection.event_type == "BOTTOM_PASSIVATION":
                bottom_passivation = detection
            elif detection.event_type == "BOTTOM_STRUCTURE":
                bottom_structure = detection
            elif detection.event_type == "TOP_PASSIVATION":
                top_passivation = detection
            elif detection.event_type == "TOP_STRUCTURE":
                top_structure = detection
    return detections


def _detect_at_index(
    series: list[tuple[KLine, Indicator]],
    index: int,
    bottom_passivation: StructureDetection | None,
    bottom_structure: StructureDetection | None,
    top_passivation: StructureDetection | None,
    top_structure: StructureDetection | None,
) -> list[StructureDetection]:
    detections: list[StructureDetection] = []
    current_bar, current_i = series[index]
    previous_bar, previous_i = series[index - 1]
    lookback = series[max(0, index - 30) : index]
    lows = [item[0].low for item in lookback]
    highs = [item[0].high for item in lookback]
    difs = [item[1].macd_dif for item in lookback if item[1].macd_dif is not None]
    if not lows or not highs or not difs or current_i.macd_dif is None or current_i.macd_hist is None or previous_i.macd_hist is None:
        return []

    near_low = current_bar.low <= min(lows) * 1.03
    dif_higher_low = current_i.macd_dif > min(difs)
    hist_improving = current_i.macd_hist > previous_i.macd_hist
    if near_low and dif_higher_low and hist_improving:
        detections.append(
            StructureDetection(
                current_bar.symbol,
                current_bar.timeframe,
                "BOTTOM_PASSIVATION",
                current_bar.ts,
                current_bar.close,
                "price near stage low while MACD DIF holds higher low and histogram improves",
            )
        )

    near_high = current_bar.high >= max(highs) * 0.97
    dif_lower_high = current_i.macd_dif < max(difs)
    hist_weakening = current_i.macd_hist < previous_i.macd_hist
    if near_high and dif_lower_high and hist_weakening:
        detections.append(
            StructureDetection(
                current_bar.symbol,
                current_bar.timeframe,
                "TOP_PASSIVATION",
                current_bar.ts,
                current_bar.close,
                "price near stage high while MACD DIF fails to confirm and histogram weakens",
            )
        )

    recent = series[max(0, index - 8) : index]
    if bottom_passivation and bottom_passivation.event_ts < current_bar.ts:
        key_high = max(item[0].high for item in recent)
        ma20_ok = current_i.ma20 is not None and current_bar.close >= current_i.ma20
        volume_ok = current_i.volume_ma20 is None or current_bar.volume >= current_i.volume_ma20 * 0.65
        dif_turning = current_i.macd_dif >= previous_i.macd_dif
        if current_bar.close >= key_high and ma20_ok and hist_improving and dif_turning and volume_ok:
            detections.append(
                StructureDetection(
                    current_bar.symbol,
                    current_bar.timeframe,
                    "BOTTOM_STRUCTURE",
                    current_bar.ts,
                    current_bar.close,
                    "bottom passivation confirmed by key high breakout, MA20 recovery, MACD improvement, and acceptable volume",
                )
            )

    if top_passivation and top_passivation.event_ts < current_bar.ts:
        key_low = min(item[0].low for item in recent)
        dif_down = current_i.macd_dif <= previous_i.macd_dif
        if current_bar.close <= key_low and hist_weakening and dif_down:
            detections.append(
                StructureDetection(
                    current_bar.symbol,
                    current_bar.timeframe,
                    "TOP_STRUCTURE",
                    current_bar.ts,
                    current_bar.close,
                    "top passivation confirmed by key low break and continued MACD weakening",
                )
            )

    if bottom_structure and bottom_structure.event_ts < current_bar.ts:
        if current_bar.close < bottom_structure.price * 0.97 and hist_weakening:
            detections.append(
                StructureDetection(
                    current_bar.symbol,
                    current_bar.timeframe,
                    "BOTTOM_FAILED",
                    current_bar.ts,
                    current_bar.close,
                    "bottom structure failed after effective low break and renewed momentum deterioration",
                )
            )

    if top_structure and top_structure.event_ts < current_bar.ts:
        if current_bar.close > top_structure.price * 1.03 and current_i.ma20 is not None and current_bar.close > current_i.ma20:
            detections.append(
                StructureDetection(
                    current_bar.symbol,
                    current_bar.timeframe,
                    "TOP_INVALIDATED",
                    current_bar.ts,
                    current_bar.close,
                    "top structure invalidated by renewed breakout with trend intact",
                )
            )
    return detections


def _latest_event(session: Session, symbol: str, timeframe: str, event_type: str) -> StructureEvent | None:
    return session.scalar(
        select(StructureEvent)
        .where(
            StructureEvent.symbol == symbol,
            StructureEvent.timeframe == timeframe,
            StructureEvent.event_type == event_type,
        )
        .order_by(StructureEvent.event_ts.desc())
        .limit(1)
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
            records.append(existing)
            continue
        event = StructureEvent(
            symbol=detection.symbol,
            timeframe=detection.timeframe,
            event_type=detection.event_type,
            event_ts=detection.event_ts,
            price=detection.price,
            reason=detection.reason,
            market_state=market_state,
            stock_trend=stock_trend,
        )
        session.add(event)
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
