from types import SimpleNamespace

from app.presentation_status import status_for
from app.services.next_action import describe_position_next_action, describe_trade_plan_next_action
from app.services.view_models import trade_plan_groups


def test_status_dictionary_has_safe_fallback():
    assert status_for("ORDER_SUBMITTED").display_name == "订单已提交"
    assert status_for("UNKNOWN_FUTURE_STATUS").display_name == "UNKNOWN_FUTURE_STATUS"


def test_trade_plan_next_action_explains_price_gate():
    plan = SimpleNamespace(
        status="ACTIVE",
        breakout_entry_price=101.5,
        no_chase_above=103.0,
    )
    text = describe_trade_plan_next_action(plan)
    assert "101.50" in text
    assert "103.00" in text


def test_position_next_action_prioritizes_stop_risk():
    position = SimpleNamespace(current_r=-0.8, partial_exit_done=False)
    assert "接近止损" in describe_position_next_action(position)


def test_trade_plan_groups_separate_execution_states():
    active = SimpleNamespace(status="ACTIVE", breakout_entry_price=101.5, no_chase_above=103.0)
    blocked = SimpleNamespace(status="BLOCKED", breakout_entry_price=None, no_chase_above=None)
    groups = trade_plan_groups([active, blocked])
    assert [group["title"] for group in groups] == ["可执行机会", "已拒绝"]
