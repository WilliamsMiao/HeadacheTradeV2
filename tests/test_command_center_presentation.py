from types import SimpleNamespace

from app.presentation_status import status_for
from app.services.next_action import describe_position_next_action, describe_trade_plan_next_action
from app.services.view_models import trade_plan_groups
from app.services.command_center import command_center_payload
from app.config import Settings
from app.models import TradePlan


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


def test_trade_plan_next_action_does_not_wait_for_breakout_inside_price_gate():
    plan = SimpleNamespace(
        status="ACTIVE",
        current_price=101,
        breakout_entry_price=100,
        no_chase_above=102,
        rules_reject_reason="",
        capital_status="CAPITAL_AVAILABLE",
        capital_reason="",
    )
    text = describe_trade_plan_next_action(plan)
    assert "等待价格突破" not in text
    assert "价格条件满足，但计划尚未完成实时校验" in text


def test_trade_plan_next_action_blocks_unknown_capital():
    plan = SimpleNamespace(
        status="TRIGGERED",
        current_price=101,
        breakout_entry_price=100,
        no_chase_above=102,
        rules_reject_reason="",
        capital_status="CAPITAL_UNKNOWN",
        capital_reason="",
    )
    assert "资金状态未知，禁止下单" in describe_trade_plan_next_action(plan)


def test_position_next_action_prioritizes_stop_risk():
    position = SimpleNamespace(current_r=-0.8, partial_exit_done=False)
    assert "接近止损" in describe_position_next_action(position)


def test_trade_plan_groups_separate_execution_states():
    active = SimpleNamespace(status="ACTIVE", breakout_entry_price=101.5, no_chase_above=103.0)
    blocked = SimpleNamespace(status="BLOCKED", breakout_entry_price=None, no_chase_above=None)
    groups = trade_plan_groups([active, blocked])
    assert [group["title"] for group in groups] == ["可执行机会", "已拒绝"]


def test_command_center_orders_s_before_a(session):
    for symbol, priority in (("AAPL", "A"), ("MSFT", "S")):
        session.add(TradePlan(
            symbol=symbol, name=symbol, direction="LONG", source_structure_id=1,
            battle_pool_id=1, structure_type="BOTTOM_STRUCTURE", priority_level=priority,
            stop_price=90, target_1=110, target_2=120, trailing_rule="test",
            time_stop_rule="test", invalid_condition="test", risk_reward_1=1.5,
            risk_reward_2=2, status="ACTIVE", reason="test",
        ))
    session.commit()

    payload = command_center_payload(session, Settings())

    assert [item["record"].priority_level for item in payload["executable"]] == ["S", "A"]
