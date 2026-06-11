from app.models import TradePlan
from app.services.plan_prices import refresh_trade_plan_prices


class QuoteProvider:
    def get_market_snapshot(self, symbols):
        assert symbols == ["AAPL", "MSFT"]
        return [
            {"code": "US.AAPL", "last_price": 201.25, "change_rate": 1.5},
            {"code": "US.MSFT", "last_price": 420.5, "change_rate": -0.25},
        ]


def _plan(symbol: str, priority: str) -> TradePlan:
    return TradePlan(
        symbol=symbol,
        name=symbol,
        direction="LONG",
        source_structure_id=1,
        battle_pool_id=1,
        structure_type="BOTTOM_STRUCTURE",
        priority_level=priority,
        stop_price=90,
        target_1=110,
        target_2=120,
        trailing_rule="test",
        time_stop_rule="test",
        invalid_condition="test",
        risk_reward_1=1.5,
        risk_reward_2=2,
        status="ACTIVE",
        reason="test",
    )


def test_refresh_trade_plan_prices_updates_live_values(session):
    session.add_all([_plan("MSFT", "A"), _plan("AAPL", "S")])
    session.commit()

    payload = refresh_trade_plan_prices(session, QuoteProvider())

    assert payload["prices"] == {"AAPL": 201.25, "MSFT": 420.5}
    assert payload["statuses"] == {"AAPL": "ACTIVE", "MSFT": "ACTIVE"}
    plans = {plan.symbol: plan for plan in session.query(TradePlan).all()}
    assert plans["AAPL"].current_price == 201.25
    assert plans["MSFT"].current_change_pct == -0.0025
