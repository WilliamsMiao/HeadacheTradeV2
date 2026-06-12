from datetime import datetime

from sqlalchemy import select

from app.config import Settings
from app.models import Indicator, MarketState, TradePlan
from app.services.realtime_execution_validator import validate_active_trade_plans


class QuoteProvider:
    def __init__(self, price):
        self.price = price

    def get_market_snapshot(self, symbols):
        return [{"code": f"US.{symbol}", "last_price": self.price, "bid_price": self.price - 0.01, "ask_price": self.price, "volume": 1000} for symbol in symbols]


def plan(symbol="AAPL", priority="S"):
    return TradePlan(
        symbol=symbol,
        source_structure_id=1,
        battle_pool_id=1,
        structure_type="BOTTOM_STRUCTURE",
        priority_level=priority,
        direction="LONG",
        breakout_entry_price=100,
        no_chase_above=102,
        stop_price=95,
        target_1=107.5,
        target_2=110,
        trailing_rule="trail",
        time_stop_rule="time",
        invalid_condition="invalid",
        risk_reward_1=1.5,
        risk_reward_2=2,
        status="ACTIVE",
        reason="test",
    )


def test_b_c_plans_are_not_realtime_trade_candidates(session):
    session.add_all([plan("B", "B"), plan("C", "C")])
    session.commit()
    result = validate_active_trade_plans(session, QuoteProvider(100), Settings())
    assert result["validated"] == 0


def test_plan_becomes_triggered_only_inside_no_chase_range(session):
    record = plan()
    session.add(record)
    session.add(MarketState(as_of=datetime.utcnow().date(), state="RISK_ON", reason="ok"))
    session.commit()
    validate_active_trade_plans(session, QuoteProvider(101), Settings())
    assert record.status == "TRIGGERED"


def test_validation_context_distinguishes_missing_and_failed_checks(session):
    record = plan()
    session.add(record)
    session.add(MarketState(as_of=datetime.utcnow().date(), state="RISK_ON", reason="ok"))
    session.commit()

    result = validate_active_trade_plans(session, QuoteProvider(101), Settings())
    context = result["contexts"][record.id]

    assert context["spread_available"] is True
    assert context["volume_available"] is True
    assert context["short_trend_ok"] is None
    assert context["market_state_available"] is True


def test_short_trend_uses_latest_60m_ma20(session):
    record = plan()
    session.add(record)
    session.add(Indicator(symbol="AAPL", timeframe="60m", ts=datetime.utcnow(), ma20=99))
    session.commit()

    result = validate_active_trade_plans(session, QuoteProvider(101), Settings())

    assert result["contexts"][record.id]["short_trend_ok"] is True


def test_plan_is_no_chase_or_invalidated(session):
    record = plan()
    session.add(record)
    session.commit()
    validate_active_trade_plans(session, QuoteProvider(103), Settings())
    assert record.status == "NO_CHASE"
    record.status = "ACTIVE"
    session.commit()
    validate_active_trade_plans(session, QuoteProvider(94), Settings())
    assert record.status == "INVALIDATED"
