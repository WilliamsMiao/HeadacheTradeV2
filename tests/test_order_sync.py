from datetime import datetime, timedelta

from app.models import Position, SimOrder, TradePlan
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


class FilledSellProvider(SimProviderWithoutDeals):
    def get_open_orders(self):
        return [{"order_id": "sell-1", "order_status": "FILLED", "dealt_qty": 5, "dealt_avg_price": 106}]


def test_sim_loop_continues_when_futu_simulation_does_not_support_deals(session):
    result = sync_sim_orders(session, SimProviderWithoutDeals())

    assert result == {"updated": 0, "filled": 0, "missing": 0, "deals_supported": False}


def test_unrelated_deal_sync_errors_are_not_hidden(session):
    try:
        sync_sim_orders(session, BrokenDealsProvider())
    except RuntimeError as exc:
        assert "OpenD connection failed" in str(exc)
    else:
        raise AssertionError("unexpected deal sync failures must still stop the loop")


def test_missing_remote_entry_order_waits_for_reconciliation_instead_of_cancel(session):
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

    assert order.status == "UNKNOWN_REMOTE_MISSING"
    assert "等待成交/持仓对账" in order.reason
    assert plan.status == "ORDER_SUBMITTED"


def test_risk_sell_order_is_not_cancelled_by_entry_timeout(session):
    order = SimOrder(
        symbol="US.EMR",
        side="SELL",
        qty=10,
        limit_price=100,
        futu_order_id="missing-sell",
        status="SUBMITTED",
        submitted_at=datetime.utcnow() - timedelta(minutes=5),
        reason="HARD_STOP",
    )
    session.add(order)
    session.commit()

    result = sync_sim_orders(session, MissingOrderProvider(), timeout_seconds=60)

    assert result["missing"] == 1
    assert order.status == "SUBMITTED"
    assert "风控卖出单" in order.reason


def test_partial_exit_flag_updates_only_after_filled_sell_order(session):
    position = Position(
        symbol="US.PART",
        status="OPEN",
        entry_price=100,
        stop_price=95,
        shares=10,
        available_shares=10,
        target_1=106,
        risk_amount=50,
    )
    order = SimOrder(
        symbol="US.PART",
        side="SELL",
        qty=5,
        limit_price=106,
        futu_order_id="sell-1",
        status="SUBMITTED",
        reason="TARGET_1_PARTIAL",
    )
    session.add_all([position, order])
    session.commit()

    result = sync_sim_orders(session, FilledSellProvider())

    assert result["filled"] == 1
    assert position.shares == 5
    assert position.partial_exit_done is True
    assert position.stop_price == 100
