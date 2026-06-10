from datetime import datetime

import pytest

from app.models import TradeSignal
from app.services.approvals import approve_signal


def test_entry_approval_requires_structure_and_trigger_sources(session):
    signal = TradeSignal(
        symbol="AAPL",
        signal_type="ENTRY",
        script="SCRIPT_A_BOTTOM_TREND_RESUME",
        action="入场候选",
        entry_price=100,
        stop_price=95,
        shares=100,
        risk_amount=500,
        reason="legacy incomplete signal",
    )
    session.add(signal)
    session.commit()

    with pytest.raises(ValueError, match="missing structure or trigger source"):
        approve_signal(session, signal.id)


def test_complete_entry_signal_can_create_simulated_position(session):
    signal = TradeSignal(
        symbol="AAPL",
        signal_type="ENTRY",
        script="SCRIPT_A_BOTTOM_TREND_RESUME",
        action="入场候选",
        entry_price=100,
        stop_price=95,
        shares=100,
        risk_amount=500,
        source_structure_id=12,
        trigger_timeframe="15m",
        trigger_ts=datetime(2026, 6, 8, 11, 15),
        trigger_level=99.5,
        reason="complete auditable signal",
    )
    session.add(signal)
    session.commit()

    approved = approve_signal(session, signal.id)

    assert approved.status == "APPROVED"
