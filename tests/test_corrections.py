from datetime import datetime, timedelta

from sqlalchemy import select

from app.models import Indicator, KLine, StructureEvent, TradeSignal
from app.services.corrections import reconcile_pending_entry


def _seed_pending_entry(session) -> tuple[StructureEvent, TradeSignal]:
    trigger_ts = datetime(2026, 6, 8, 11, 15)
    structure = StructureEvent(
        symbol="AAPL",
        timeframe="60m",
        event_type="BOTTOM_STRUCTURE",
        event_ts=datetime(2026, 6, 8, 10),
        price=100,
        pivot_low=95,
        invalidation_level=95,
        expires_at=datetime(2026, 6, 20),
        reason="bottom",
    )
    session.add(structure)
    session.flush()
    signal = TradeSignal(
        symbol="AAPL",
        signal_type="ENTRY",
        script="SCRIPT_A_BOTTOM_TREND_RESUME",
        action="入场候选",
        entry_price=102,
        stop_price=94,
        shares=100,
        risk_amount=800,
        source_structure_id=structure.id,
        trigger_timeframe="15m",
        trigger_ts=trigger_ts,
        trigger_level=101,
        reason="entry",
    )
    session.add(signal)
    session.add(
        Indicator(
            symbol="AAPL",
            timeframe="15m",
            ts=trigger_ts,
            ma20=100,
            macd_dif=0.3,
            macd_hist=0.2,
        )
    )
    session.commit()
    return structure, signal


def _add_post_trigger_bar(session, index: int, *, close: float, ma20: float, histogram: float) -> None:
    ts = datetime(2026, 6, 8, 11, 15) + timedelta(minutes=15 * index)
    session.add(
        KLine(
            symbol="AAPL",
            timeframe="15m",
            ts=ts,
            open=close,
            high=close + 0.2,
            low=close - 0.2,
            close=close,
            volume=800_000,
        )
    )
    session.add(
        Indicator(
            symbol="AAPL",
            timeframe="15m",
            ts=ts,
            ma20=ma20,
            macd_dif=0.3,
            macd_hist=histogram,
        )
    )
    session.commit()


def test_bottom_failure_cancels_related_pending_entry(session):
    structure, signal = _seed_pending_entry(session)
    session.add(
        StructureEvent(
            symbol="AAPL",
            timeframe="60m",
            event_type="BOTTOM_FAILED",
            event_ts=datetime(2026, 6, 8, 12),
            price=94,
            parent_event_id=structure.id,
            reason="failed",
        )
    )
    session.commit()

    result = reconcile_pending_entry(session, "AAPL", "RISK_ON")

    assert result is not None
    assert result.status == "CANCELLED_BY_STRUCTURE"
    assert result.start_cooldown is True
    assert signal.status == "CANCELLED_BY_STRUCTURE"
    assert signal.cancel_reason


def test_trigger_failure_cancels_pending_entry(session):
    _, signal = _seed_pending_entry(session)
    _add_post_trigger_bar(session, 1, close=100.5, ma20=100, histogram=0.3)

    result = reconcile_pending_entry(session, "AAPL", "RISK_ON")

    assert result is not None
    assert result.status == "CANCELLED_BY_TRIGGER"
    assert signal.status == "CANCELLED_BY_TRIGGER"
    assert "触发位" in (signal.cancel_reason or "")


def test_market_downgrade_cancels_pending_entry(session):
    _, signal = _seed_pending_entry(session)

    result = reconcile_pending_entry(session, "AAPL", "RISK_OFF")

    assert result is not None
    assert result.status == "CANCELLED_BY_MARKET"
    assert signal.status == "CANCELLED_BY_MARKET"
    assert "风险关闭" in (signal.cancel_reason or "")


def test_pending_entry_expires_after_configured_15m_bars(session):
    _, signal = _seed_pending_entry(session)
    for index in range(1, 5):
        _add_post_trigger_bar(
            session,
            index,
            close=102 + index * 0.1,
            ma20=100,
            histogram=0.2 + index * 0.1,
        )

    result = reconcile_pending_entry(session, "AAPL", "RISK_ON")

    assert result is not None
    assert result.status == "EXPIRED"
    assert signal.status == "EXPIRED"
    assert "4 根" in (signal.cancel_reason or "")
    assert session.scalar(select(TradeSignal).where(TradeSignal.status == "PENDING")) is None
