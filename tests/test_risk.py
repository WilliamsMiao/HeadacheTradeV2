from datetime import datetime

from app.models import Indicator, RiskConfig, StructureEvent
from app.services.risk import calculate_position_size, calculate_structure_stop


def test_no_stop_means_no_entry_position_size():
    config = RiskConfig(account_equity=100000, risk_per_trade_pct=0.01, max_symbol_position_pct=0.2)
    assert calculate_position_size(config, entry_price=100, stop_price=None, market_state="RISK_ON", script="SCRIPT_A_BOTTOM_TREND_RESUME") is None
    assert calculate_position_size(config, entry_price=100, stop_price=101, market_state="RISK_ON", script="SCRIPT_A_BOTTOM_TREND_RESUME") is None


def test_script_b_uses_lower_risk():
    config = RiskConfig(account_equity=100000, risk_per_trade_pct=0.01, script_b_risk_multiplier=0.5, max_symbol_position_pct=1)
    a = calculate_position_size(config, 100, 95, "RISK_ON", "SCRIPT_A_BOTTOM_TREND_RESUME")
    b = calculate_position_size(config, 100, 95, "RISK_ON", "SCRIPT_B_TOP_INVALIDATION_CONTINUATION")
    assert a is not None
    assert b is not None
    assert b.allowed_loss == a.allowed_loss * 0.5
    assert b.shares == a.shares // 2


def test_script_a_stop_uses_60m_pivot_and_atr(session):
    ts = datetime(2026, 6, 8, 10)
    structure = StructureEvent(
        symbol="AAPL",
        timeframe="60m",
        event_type="BOTTOM_STRUCTURE",
        event_ts=ts,
        price=100,
        pivot_low=95,
        reason="bottom",
    )
    session.add(structure)
    session.add(Indicator(symbol="AAPL", timeframe="60m", ts=ts, atr=4))
    session.commit()

    stop = calculate_structure_stop(session, structure, 102, "SCRIPT_A_BOTTOM_TREND_RESUME")

    assert stop is not None
    assert stop.reference_level == 95
    assert stop.atr == 4
    assert stop.stop_price == 93


def test_structure_stop_requires_pivot_and_60m_atr(session):
    ts = datetime(2026, 6, 8, 10)
    structure = StructureEvent(
        symbol="AAPL",
        timeframe="60m",
        event_type="BOTTOM_STRUCTURE",
        event_ts=ts,
        price=100,
        reason="bottom",
    )
    session.add(structure)
    session.commit()

    assert calculate_structure_stop(session, structure, 102, "SCRIPT_A_BOTTOM_TREND_RESUME") is None

    structure.pivot_low = 95
    session.add(Indicator(symbol="AAPL", timeframe="60m", ts=ts, atr=None))
    session.commit()
    assert calculate_structure_stop(session, structure, 102, "SCRIPT_A_BOTTOM_TREND_RESUME") is None


def test_structure_stop_does_not_fall_back_to_older_atr(session):
    ts = datetime(2026, 6, 8, 10)
    structure = StructureEvent(
        symbol="AAPL",
        timeframe="60m",
        event_type="BOTTOM_STRUCTURE",
        event_ts=ts,
        price=100,
        pivot_low=95,
        reason="bottom",
    )
    session.add(structure)
    session.add(Indicator(symbol="AAPL", timeframe="60m", ts=datetime(2026, 6, 8, 9), atr=4))
    session.commit()

    assert calculate_structure_stop(session, structure, 102, "SCRIPT_A_BOTTOM_TREND_RESUME") is None


def test_script_b_stop_is_tighter_and_position_risk_is_discounted(session):
    ts = datetime(2026, 6, 8, 10)
    structure = StructureEvent(
        symbol="AAPL",
        timeframe="60m",
        event_type="TOP_INVALIDATED",
        event_ts=ts,
        price=102,
        invalidation_level=100,
        reason="top invalidated",
    )
    session.add(structure)
    session.add(Indicator(symbol="AAPL", timeframe="60m", ts=ts, atr=4))
    session.commit()

    stop = calculate_structure_stop(session, structure, 104, "SCRIPT_B_TOP_INVALIDATION_CONTINUATION")
    assert stop is not None
    assert stop.stop_price == 99
