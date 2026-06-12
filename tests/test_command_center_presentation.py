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
    assert "价格已经进入允许入场的区间" in text


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
    assert "暂时无法确认账户是否有足够资金" in describe_trade_plan_next_action(plan)


def test_trade_plan_checks_use_natural_language(session):
    session.add(TradePlan(
        symbol="AAPL", name="Apple", direction="LONG", source_structure_id=1,
        battle_pool_id=1, structure_type="BOTTOM_STRUCTURE", priority_level="S",
        breakout_entry_price=175, no_chase_above=180.14, current_price=180.77,
        stop_price=170, target_1=185, target_2=190, trailing_rule="test",
        time_stop_rule="test", invalid_condition="test", risk_reward_1=1.5,
        risk_reward_2=2, status="ACTIVE", reason="test",
    ))
    session.commit()

    item = command_center_payload(session, Settings())["executable"][0]

    price_check = next(check for check in item["checks"] if check["label"] == "当前价格仍适合入场")
    assert "当前价 180.77 已高于最高可接受入场价 180.14" in price_check["detail"]
    assert "为避免追高" in price_check["detail"]
    assert all(">=" not in check["label"] and "<=" not in check["label"] for check in item["checks"])
    assert all("TRIGGERED" not in check["detail"] and "ACTIVE" not in check["detail"] for check in item["checks"])


def test_position_next_action_prioritizes_stop_risk():
    position = SimpleNamespace(current_r=-0.8, partial_exit_done=False)
    assert "接近止损" in describe_position_next_action(position)


def test_trade_plan_groups_separate_execution_states(session):
    plans = []
    for symbol, status in (("AAPL", "ACTIVE"), ("MSFT", "BLOCKED")):
        plan = TradePlan(
            symbol=symbol, name=symbol, direction="LONG", source_structure_id=1,
            battle_pool_id=1, structure_type="BOTTOM_STRUCTURE", priority_level="A",
            stop_price=90, target_1=110, target_2=120, trailing_rule="test",
            time_stop_rule="test", invalid_condition="test", risk_reward_1=1.5,
            risk_reward_2=2, status=status, reason="test",
        )
        session.add(plan)
        plans.append(plan)
    session.commit()
    groups = trade_plan_groups(session, plans, Settings())
    assert [group["title"] for group in groups] == ["待触发计划", "执行阻塞"]


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
