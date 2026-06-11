from datetime import datetime, timedelta

from app.models import Indicator, KLine, StructureEvent
from app.services.structures import (
    StructureDetection,
    _detect_at_index,
    detect_latest_structures,
    persist_structure_detections,
)
from app.strategy_config import STRUCTURE_CONFIG


def _series(count: int = 40):
    start = datetime(2026, 1, 1, 9, 30)
    output = []
    for index in range(count):
        close = 100.0
        bar = KLine(
            symbol="AAPL",
            timeframe="60m",
            ts=start + timedelta(hours=index),
            open=close,
            high=101,
            low=99,
            close=close,
            volume=1_000_000,
        )
        indicator = Indicator(
            symbol="AAPL",
            timeframe="60m",
            ts=bar.ts,
            ma20=100,
            ma60=99,
            macd_dif=-0.6,
            macd_dea=-0.7,
            macd_hist=0.1,
            atr=2,
            volume_ma20=900_000,
        )
        output.append((bar, indicator))
    return output


def test_bottom_structure_contains_required_levels():
    series = _series()
    current_bar, current_i = series[-1]
    current_bar.close = 102
    current_bar.high = 103
    current_i.macd_dif = -0.4
    current_i.macd_hist = 0.5
    passivation = StructureDetection(
        symbol="AAPL",
        timeframe="60m",
        event_type="BOTTOM_PASSIVATION",
        event_ts=current_bar.ts - timedelta(hours=1),
        price=99,
        reason="passivation",
        pivot_low=95,
        invalidation_level=95,
    )

    detections = _detect_at_index(series, len(series) - 1, passivation, None, None, None)
    bottom = next(item for item in detections if item.event_type == "BOTTOM_STRUCTURE")

    assert bottom.pivot_low == 95
    assert bottom.confirm_level == 101
    assert bottom.invalidation_level == 95
    assert bottom.expires_at is not None
    assert bottom.script_version == STRUCTURE_CONFIG.script_version


def test_top_structure_contains_required_levels():
    series = _series()
    current_bar, current_i = series[-1]
    current_bar.close = 98
    current_bar.low = 97
    current_i.macd_dif = -0.8
    current_i.macd_hist = -0.2
    passivation = StructureDetection(
        symbol="AAPL",
        timeframe="60m",
        event_type="TOP_PASSIVATION",
        event_ts=current_bar.ts - timedelta(hours=1),
        price=101,
        reason="passivation",
        pivot_high=105,
        invalidation_level=105,
    )

    detections = _detect_at_index(series, len(series) - 1, None, None, passivation, None)
    top = next(item for item in detections if item.event_type == "TOP_STRUCTURE")

    assert top.pivot_high == 105
    assert top.confirm_level == 99
    assert top.invalidation_level == 105
    assert top.expires_at is not None


def test_failure_and_invalidation_link_to_parent_events(session):
    start = datetime(2026, 1, 1)
    bottom = StructureDetection(
        symbol="AAPL",
        timeframe="60m",
        event_type="BOTTOM_STRUCTURE",
        event_ts=start,
        price=101,
        reason="bottom confirmed",
        pivot_low=95,
        confirm_level=101,
        invalidation_level=95,
        expires_at=start + timedelta(days=14),
    )
    failed = StructureDetection(
        symbol="AAPL",
        timeframe="60m",
        event_type="BOTTOM_FAILED",
        event_ts=start + timedelta(hours=1),
        price=94,
        reason="bottom failed",
        pivot_low=95,
        invalidation_level=95,
        parent_event_type="BOTTOM_STRUCTURE",
        parent_event_ts=start,
    )
    top = StructureDetection(
        symbol="AAPL",
        timeframe="60m",
        event_type="TOP_STRUCTURE",
        event_ts=start + timedelta(hours=2),
        price=99,
        reason="top confirmed",
        pivot_high=105,
        confirm_level=99,
        invalidation_level=105,
        expires_at=start + timedelta(days=14),
    )
    invalidated = StructureDetection(
        symbol="AAPL",
        timeframe="60m",
        event_type="TOP_INVALIDATED",
        event_ts=start + timedelta(hours=3),
        price=106,
        reason="top invalidated",
        pivot_high=105,
        invalidation_level=105,
        parent_event_type="TOP_STRUCTURE",
        parent_event_ts=top.event_ts,
    )

    records = persist_structure_detections(session, [bottom, failed, top, invalidated], "RISK_ON", "UPTREND")
    bottom_record, failed_record, top_record, invalidated_record = records

    assert failed_record.parent_event_id == bottom_record.id
    assert bottom_record.became_failed is True
    assert bottom_record.invalidated is True
    assert invalidated_record.parent_event_id == top_record.id
    assert top_record.invalidated is True


def test_active_lifecycle_does_not_repeat_same_structure():
    series = _series()
    current_bar, current_i = series[-1]
    current_bar.close = 102
    current_bar.high = 103
    current_i.macd_dif = -0.4
    current_i.macd_hist = 0.5
    passivation = StructureDetection(
        symbol="AAPL",
        timeframe="60m",
        event_type="BOTTOM_PASSIVATION",
        event_ts=current_bar.ts - timedelta(hours=2),
        price=99,
        reason="passivation",
        pivot_low=95,
    )
    active = StructureDetection(
        symbol="AAPL",
        timeframe="60m",
        event_type="BOTTOM_STRUCTURE",
        event_ts=current_bar.ts - timedelta(hours=1),
        price=101,
        reason="active",
        pivot_low=95,
        confirm_level=101,
        invalidation_level=95,
    )

    detections = _detect_at_index(series, len(series) - 1, passivation, active, None, None)
    assert not any(item.event_type == "BOTTOM_STRUCTURE" for item in detections)


def test_structure_events_are_deduplicated(session):
    event = StructureDetection(
        symbol="AAPL",
        timeframe="60m",
        event_type="BOTTOM_STRUCTURE",
        event_ts=datetime(2026, 1, 1),
        price=101,
        reason="confirmed",
        pivot_low=95,
        confirm_level=101,
        invalidation_level=95,
        expires_at=datetime(2026, 1, 15),
    )
    first = persist_structure_detections(session, [event], "RISK_ON", "UPTREND")
    second = persist_structure_detections(session, [event], "RISK_ON", "UPTREND")

    assert first[0].id == second[0].id
    assert session.query(StructureEvent).count() == 1


def test_detected_structures_are_persistable(session):
    start = datetime(2025, 1, 1)
    for index in range(60):
        close = 100 - min(index, 35) * 0.5 + max(0, index - 40) * 1.5
        session.add(
            KLine(
                symbol="AAPL",
                timeframe="60m",
                ts=start + timedelta(hours=index),
                open=close,
                high=close + 1,
                low=close - 1,
                close=close,
                volume=1_000_000,
            )
        )
        session.add(
            Indicator(
                symbol="AAPL",
                timeframe="60m",
                ts=start + timedelta(hours=index),
                ma20=close - 0.5,
                ma60=close - 2,
                macd_dif=-2 + index * 0.05,
                macd_dea=-2,
                macd_hist=-1 + index * 0.04,
                atr=2,
                volume_ma20=900_000,
            )
        )
    session.commit()

    detections = detect_latest_structures(session, "AAPL", "60m")
    records = persist_structure_detections(session, detections, "RISK_ON", "UPTREND")
    assert len(records) == len(detections)
