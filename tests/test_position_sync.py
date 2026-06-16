import json
from datetime import datetime, timedelta

from app.config import Settings
from app.models import AuditLog, Position, SimOrder, TradePlan
from app.services.position_manager import manage_positions
from app.services.position_sync import sync_futu_positions_to_local


class PositionProvider:
    def __init__(self, positions, *, order_error: str = ""):
        self.positions = positions
        self.order_error = order_error
        self.orders = []

    def get_positions(self):
        return self.positions

    def place_simulated_order(self, symbol, side, quantity, price):
        if self.order_error:
            raise RuntimeError(self.order_error)
        self.orders.append((symbol, side, quantity, price))
        return {"order_id": f"order-{len(self.orders)}"}


class QuoteProvider:
    def __init__(self, prices=None):
        self.prices = prices or {}

    def get_market_snapshot(self, symbols):
        return [
            {"code": symbol, "last_price": self.prices[symbol], "bid_price": self.prices[symbol] - 0.2}
            for symbol in symbols
            if symbol in self.prices
        ]


def futu_position(symbol="US.EMR", price=103, quantity=100, available=100):
    return {
        "code": symbol,
        "stock_name": "Emerson Electric",
        "qty": quantity,
        "can_sell_qty": available,
        "cost_price": 100,
        "nominal_price": price,
        "market_val": price * quantity,
        "pl_val": (price - 100) * quantity,
    }


def test_futu_only_holding_becomes_managed_orphan_position(session):
    provider = PositionProvider([futu_position()])

    result = sync_futu_positions_to_local(session, provider, Settings())

    position = session.query(Position).one()
    assert result["created"] == 1
    assert position.symbol == "US.EMR"
    assert position.entry_signal_id == 0
    assert position.source == "FUTU_DETECTED"
    assert position.is_orphan is True
    assert position.shares == 100
    assert position.available_shares == 100
    assert position.stop_price == 98
    assert position.target_1 == 103
    assert session.query(AuditLog).filter_by(action="ORPHAN_POSITION_DETECTED").count() == 1


def test_orphan_position_reaching_default_profit_submits_sell_order(session):
    provider = PositionProvider([futu_position(price=103.1, available=80)])
    settings = Settings(force_intraday_exit=False)
    sync_futu_positions_to_local(session, provider, settings)

    result = manage_positions(session, QuoteProvider(), provider, settings)

    order = session.query(SimOrder).one()
    assert result["exit_orders_submitted"] == 1
    assert provider.orders == [("US.EMR", "SELL", 80, 102.58)]
    assert order.side == "SELL"
    assert order.qty == 80
    assert order.reason == "ORPHAN_TAKE_PROFIT"


def test_zero_sellable_quantity_is_preserved_and_exit_is_skipped(session):
    provider = PositionProvider([futu_position(price=103.1, available=0)])
    settings = Settings()
    sync_futu_positions_to_local(session, provider, settings)

    result = manage_positions(session, QuoteProvider(), provider, settings)

    position = session.query(Position).one()
    assert position.available_shares == 0
    assert result["skipped"] == 1
    assert provider.orders == []
    assert "sellable_qty = 0" in position.last_error


def test_missing_local_position_does_not_depend_on_old_order_record(session):
    session.add(
        SimOrder(
            symbol="US.EMR",
            side="BUY",
            qty=100,
            limit_price=100,
            futu_order_id="missing-order",
            status="CANCELLED",
            reason="远端订单不存在",
        )
    )
    session.commit()
    provider = PositionProvider([futu_position(price=103.5)])

    sync_futu_positions_to_local(session, provider, Settings())
    result = manage_positions(session, QuoteProvider(), provider, Settings())

    assert result["exit_orders_submitted"] == 1
    assert session.query(Position).filter_by(symbol="US.EMR", status="OPEN").count() == 1
    assert session.query(SimOrder).filter_by(side="SELL", status="SUBMITTED").count() == 1


def test_remote_position_binds_unresolved_local_buy_order_and_plan(session):
    plan = TradePlan(
        symbol="US.EMR",
        source_structure_id=1,
        battle_pool_id=1,
        structure_type="BOTTOM_STRUCTURE",
        priority_level="S",
        direction="LONG",
        stop_price=95,
        target_1=110,
        target_2=120,
        trailing_rule="trail",
        time_stop_rule="time",
        invalid_condition="invalid",
        risk_reward_1=1.5,
        risk_reward_2=2,
        status="ORDER_SUBMITTED",
        reason="test",
    )
    session.add(plan)
    session.flush()
    order = SimOrder(
        trade_plan_id=plan.id,
        symbol="US.EMR",
        side="BUY",
        qty=100,
        limit_price=100,
        futu_order_id="missing-order",
        status="UNKNOWN_REMOTE_MISSING",
    )
    session.add(order)
    session.commit()

    sync_futu_positions_to_local(session, PositionProvider([futu_position(price=103)]), Settings())

    position = session.query(Position).filter_by(symbol="US.EMR").one()
    assert position.source == "LOCAL_AND_FUTU_CONFIRMED"
    assert position.is_orphan is False
    assert position.source_trade_plan_id == plan.id
    assert position.entry_order_id == order.id
    assert order.status == "FILLED_INFERRED"
    assert order.dealt_qty == 100
    assert plan.status == "IN_POSITION"


def test_one_position_failure_does_not_block_other_positions(session):
    session.add_all(
        [
            Position(
                symbol="US.BAD",
                status="OPEN",
                entry_price=100,
                stop_price=98,
                shares=10,
                available_shares=10,
                risk_amount=20,
                source="FUTU_DETECTED",
                is_orphan=True,
            ),
            Position(
                symbol="US.GOOD",
                status="OPEN",
                entry_price=100,
                stop_price=98,
                shares=10,
                available_shares=10,
                current_price=103.5,
                risk_amount=20,
                source="FUTU_DETECTED",
                is_orphan=True,
            ),
        ]
    )
    session.commit()
    provider = PositionProvider([])

    result = manage_positions(session, QuoteProvider(), provider, Settings())

    assert result["managed"] == 2
    assert result["errors"] == 1
    assert result["exit_orders_submitted"] == 1
    assert provider.orders == [("US.GOOD", "SELL", 10, 102.98)]


def test_target_one_partial_is_confirmed_only_after_sell_fill(session):
    provider = PositionProvider([])
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
    session.add(position)
    session.commit()

    manage_positions(session, QuoteProvider({"US.PART": 106.5}), provider, Settings(force_intraday_exit=False))

    order = session.query(SimOrder).one()
    assert order.reason == "TARGET_1_PARTIAL"
    assert provider.orders == [("US.PART", "SELL", 5, 106.3)]
    assert position.partial_exit_done is False


def test_sell_order_failure_is_recorded_without_stopping_loop(session):
    provider = PositionProvider(
        [futu_position(price=103.5)],
        order_error="Futu simulated sell failed",
    )
    sync_futu_positions_to_local(session, provider, Settings())

    result = manage_positions(session, QuoteProvider(), provider, Settings())

    position = session.query(Position).one()
    assert result["errors"] == 1
    assert "sell failed" in position.last_error
    assert session.query(AuditLog).filter_by(action="POSITION_EXIT_ORDER_FAILED").count() == 1


def test_waiting_sell_order_retries_after_reconcile_window(session):
    provider = PositionProvider([futu_position(price=94, available=100)])
    position = Position(
        symbol="US.EMR",
        status="OPEN",
        entry_price=100,
        stop_price=95,
        shares=100,
        available_shares=100,
        current_price=94,
        risk_amount=500,
        source="FUTU_DETECTED",
        is_orphan=True,
        last_synced_at=datetime.utcnow(),
        exit_reason="HARD_STOP",
    )
    order = SimOrder(
        symbol="US.EMR",
        side="SELL",
        qty=100,
        limit_price=94,
        futu_order_id="old-sell",
        status="SELL_WAITING_RECONCILIATION",
        reason="HARD_STOP；风控卖出单未在 open orders 返回，等待持仓/成交对账确认",
        submitted_at=datetime.utcnow() - timedelta(minutes=5),
        retry_count=0,
    )
    session.add_all([position, order])
    session.commit()

    result = manage_positions(
        session,
        QuoteProvider({"US.EMR": 94}),
        provider,
        Settings(force_intraday_exit=False, sell_reconcile_retry_seconds=120, max_exit_order_retries=3),
    )

    retried = session.query(SimOrder).filter_by(futu_order_id="order-1").one()
    assert result["exit_orders_submitted"] == 1
    assert retried.retry_count == 1
    assert provider.orders == [("US.EMR", "SELL", 100, 93.8)]
    assert session.query(AuditLog).filter_by(action="EXIT_ORDER_RETRIED").count() == 1


def test_waiting_sell_order_before_retry_window_is_held(session):
    provider = PositionProvider([futu_position(price=94, available=100)])
    session.add_all(
        [
            Position(
                symbol="US.EMR",
                status="OPEN",
                entry_price=100,
                stop_price=95,
                shares=100,
                available_shares=100,
                current_price=94,
                risk_amount=500,
                source="FUTU_DETECTED",
                is_orphan=True,
                last_synced_at=datetime.utcnow(),
                exit_reason="HARD_STOP",
            ),
            SimOrder(
                symbol="US.EMR",
                side="SELL",
                qty=100,
                limit_price=94,
                futu_order_id="old-sell",
                status="SELL_WAITING_RECONCILIATION",
                reason="HARD_STOP",
                submitted_at=datetime.utcnow() - timedelta(seconds=30),
            ),
        ]
    )
    session.commit()

    result = manage_positions(
        session,
        QuoteProvider({"US.EMR": 94}),
        provider,
        Settings(force_intraday_exit=False, sell_reconcile_retry_seconds=120),
    )

    assert result["exit_orders_submitted"] == 0
    assert provider.orders == []
    assert session.query(AuditLog).filter_by(action="EXIT_ORDER_RETRIED").count() == 0


def test_waiting_sell_order_retry_limit_is_not_resubmitted(session):
    provider = PositionProvider([futu_position(price=94, available=100)])
    position = Position(
        symbol="US.EMR",
        status="OPEN",
        entry_price=100,
        stop_price=95,
        shares=100,
        available_shares=100,
        current_price=94,
        risk_amount=500,
        source="FUTU_DETECTED",
        is_orphan=True,
        last_synced_at=datetime.utcnow(),
        exit_reason="HARD_STOP",
    )
    order = SimOrder(
        symbol="US.EMR",
        side="SELL",
        qty=100,
        limit_price=94,
        futu_order_id="old-sell",
        status="SELL_WAITING_RECONCILIATION",
        reason="HARD_STOP",
        submitted_at=datetime.utcnow() - timedelta(minutes=5),
        retry_count=3,
    )
    session.add_all([position, order])
    session.commit()

    result = manage_positions(
        session,
        QuoteProvider({"US.EMR": 94}),
        provider,
        Settings(force_intraday_exit=False, sell_reconcile_retry_seconds=120, max_exit_order_retries=3),
    )

    assert result["exit_orders_submitted"] == 0
    assert provider.orders == []
    assert "最大重试次数" in position.last_error
    assert session.query(AuditLog).filter_by(action="EXIT_ORDER_RETRY_LIMIT_REACHED").count() == 1


def test_multiple_buy_orders_do_not_low_confidence_bind(session):
    plan = TradePlan(
        symbol="US.EMR", source_structure_id=1, battle_pool_id=1,
        structure_type="BOTTOM_STRUCTURE", priority_level="S", direction="LONG",
        stop_price=95, target_1=110, target_2=120, trailing_rule="trail",
        time_stop_rule="time", invalid_condition="invalid", risk_reward_1=1.5,
        risk_reward_2=2, status="ORDER_SUBMITTED", reason="test",
    )
    session.add(plan)
    session.flush()
    session.add_all(
        [
            SimOrder(trade_plan_id=plan.id, symbol="US.EMR", side="BUY", qty=50, limit_price=100, status="UNKNOWN_REMOTE_MISSING"),
            SimOrder(
                trade_plan_id=plan.id,
                symbol="US.EMR",
                side="BUY",
                qty=100,
                limit_price=120,
                status="UNKNOWN_REMOTE_MISSING",
                submitted_at=datetime.utcnow() - timedelta(days=2),
            ),
        ]
    )
    session.commit()

    sync_futu_positions_to_local(session, PositionProvider([futu_position(price=103, quantity=100)]), Settings())

    position = session.query(Position).filter_by(symbol="US.EMR").one()
    assert position.source == "FUTU_DETECTED"
    assert position.is_orphan is True
    assert position.source_trade_plan_id is None
    assert position.entry_order_id is None
    assert session.query(SimOrder).filter_by(status="FILLED_INFERRED").count() == 0
    assert plan.status == "ORDER_SUBMITTED"
    assert session.query(AuditLog).filter_by(action="ORPHAN_POSITION_MATCH_LOW_CONFIDENCE").count() == 1


def test_high_confidence_buy_order_binds_with_match_payload(session):
    plan = TradePlan(
        symbol="US.EMR", source_structure_id=1, battle_pool_id=1,
        structure_type="BOTTOM_STRUCTURE", priority_level="S", direction="LONG",
        stop_price=95, target_1=110, target_2=120, trailing_rule="trail",
        time_stop_rule="time", invalid_condition="invalid", risk_reward_1=1.5,
        risk_reward_2=2, status="ORDER_SUBMITTED", reason="test",
    )
    session.add(plan)
    session.flush()
    order = SimOrder(
        trade_plan_id=plan.id,
        symbol="US.EMR",
        side="BUY",
        qty=100,
        limit_price=100.2,
        status="UNKNOWN_REMOTE_MISSING",
        submitted_at=datetime.utcnow() - timedelta(minutes=10),
    )
    session.add(order)
    session.commit()

    sync_futu_positions_to_local(session, PositionProvider([futu_position(price=103, quantity=100)]), Settings())

    position = session.query(Position).filter_by(symbol="US.EMR").one()
    audit = session.query(AuditLog).filter_by(action="SIM_ORDER_FILLED_INFERRED").one()
    payload = json.loads(audit.payload_json)
    assert position.source == "LOCAL_AND_FUTU_CONFIRMED"
    assert position.is_orphan is False
    assert order.status == "FILLED_INFERRED"
    assert order.dealt_qty == 100
    assert order.dealt_avg_price == 100
    assert plan.status == "IN_POSITION"
    assert payload["match_confidence"] == "HIGH"


def test_remote_position_missing_without_filled_sell_becomes_closed_unverified(session):
    position = Position(
        symbol="US.EMR",
        status="OPEN",
        entry_price=100,
        stop_price=95,
        shares=100,
        available_shares=100,
        risk_amount=500,
        source="FUTU_DETECTED",
        is_orphan=True,
    )
    session.add(position)
    session.commit()

    sync_futu_positions_to_local(session, PositionProvider([]), Settings())

    assert position.status == "CLOSED_UNVERIFIED"
    assert position.close_verified is False
    assert position.exit_price is None
    assert position.realized_pnl is None
    assert session.query(AuditLog).filter_by(action="POSITION_RECONCILED_CLOSED_UNVERIFIED").count() == 1
