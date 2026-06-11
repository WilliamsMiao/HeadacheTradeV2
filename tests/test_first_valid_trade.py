from app.config import Settings
from app.models import TradePlan
from app.providers.mock_trade_provider import MockTradeProvider
from app.services.sim_order_executor import execute_approved_sim_orders


def approved_plan(symbol, validated_order):
    return TradePlan(
        symbol=symbol,
        source_structure_id=validated_order,
        battle_pool_id=validated_order,
        structure_type="BOTTOM_STRUCTURE",
        priority_level="S",
        direction="LONG",
        breakout_entry_price=100,
        current_price=101,
        no_chase_above=102,
        stop_price=95,
        target_1=107.5,
        target_2=110,
        suggested_shares=10,
        trailing_rule="trail",
        time_stop_rule="time",
        invalid_condition="invalid",
        risk_reward_1=1.5,
        risk_reward_2=2,
        status="TRIGGERED",
        rules_approval_status="APPROVED_FOR_SIM_TRADE",
        reason="test",
    )


def test_first_fully_valid_plan_wins_available_capital(session):
    first_valid = approved_plan("LATER_STRUCTURE_FIRST_VALID", 2)
    later_valid = approved_plan("EARLY_STRUCTURE_SECOND_VALID", 1)
    session.add_all([first_valid, later_valid])
    session.commit()
    result = execute_approved_sim_orders(
        session,
        MockTradeProvider(),
        Settings(enable_sim_trading=True),
    )
    assert result["submitted"] == 1
    assert first_valid.status == "ORDER_SUBMITTED"
    assert later_valid.status == "TRIGGERED"
