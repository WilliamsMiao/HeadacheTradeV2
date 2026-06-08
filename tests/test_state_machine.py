from datetime import date

from app.models import KLine, TradingState
from app.services.state_machine import advance_state_machine
from sqlalchemy import select


def test_data_missing_does_not_advance_to_entry(session):
    state = advance_state_machine(session, "AAPL", "RISK_ON", "UPTREND")
    assert state.state == "IDLE"
    assert "data missing" in state.last_reason


def test_cooldown_blocks_entry(session):
    session.add(TradingState(symbol="AAPL", state="TREND_OK", cooldown_until=date.today()))
    session.commit()
    state = advance_state_machine(session, "AAPL", "RISK_ON", "UPTREND")
    assert state.state == "COOLDOWN"

