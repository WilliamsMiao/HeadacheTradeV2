from datetime import datetime, timedelta

from app.models import SimOrder, TradePlan
from app.services.order_sync import sync_sim_orders


class SimProviderWithoutDeals:
    def get_open_orders(self):
        return []

    def get_deals(self):
        raise RuntimeError("Futu simulated deal_list_query failed: 模拟交易不支持成交数据")


class BrokenDealsProvider(SimProviderWithoutDeals):
    def get_deals(self):
        raise RuntimeError("OpenD connection failed")


class MissingOrderProvider(SimProviderWithoutDeals):
    def cancel_order(self, order_id):
        raise RuntimeError("Futu simulated cancel_order failed: 此订单号不存在")


def test_sim_loop_continues_when_futu_simulation_does_not_support_deals(session):
    result = sync_sim_orders(session, SimProviderWithoutDeals())

    assert result == {"updated": 0, "filled": 0, "deals_supported": False}


def test_unrelated_deal_sync_errors_are_not_hidden(session):
    try:
        sync_sim_orders(session, BrokenDealsProvider())
    except RuntimeError as exc:
        assert "OpenD connection failed" in str(exc)
    else:
        raise AssertionError("unexpected deal sync failures must still stop the loop")


def test_missing_remote_order_is_closed_locally_without_repeated_cancel(session):
    plan = TradePlan(
        symbol="US.AAPL", source_structure_id=1, battle_pool_id=1,
        structure_type="BOTTOM_STRUCTURE", priority_level="S", direction="LONG",
        stop_price=90, target_1=110, target_2=120, trailing_rule="trail",
        time_stop_rule="time", invalid_condition="invalid", risk_reward_1=1.5,
        risk_reward_2=2, status="ORDER_SUBMITTED", reason="test",
    )
    session.add(plan)
    session.flush()
    order = SimOrder(
        trade_plan_id=plan.id,
        symbol="US.AAPL",
        side="BUY",
        qty=10,
        limit_price=100,
        futu_order_id="missing-order",
        status="SUBMITTED",
        submitted_at=datetime.utcnow() - timedelta(minutes=5),
    )
    session.add(order)
    session.commit()

    sync_sim_orders(session, MissingOrderProvider(), timeout_seconds=60)

    assert order.status == "CANCELLED"
    assert "停止重复撤单" in order.reason
    assert plan.status == "ARMED"
