from datetime import datetime, timedelta

from app.config import Settings
from app.models import Position, ReconciliationIssue, SimOrder, SystemConfig
from app.services.position_manager import manage_positions
from app.services.sim_loop import run_sim_loop
from app.services.terminal_api import terminal_summary
from app.services.trade_reconciler import run_trade_reconciliation


class ReconcileProvider:
    def __init__(self, *, positions=None, orders=None, deals=None, deals_error: str = ""):
        self.positions = positions or []
        self.orders = orders or []
        self.deals = deals or []
        self.deals_error = deals_error

    def get_positions(self):
        return self.positions

    def get_open_orders(self):
        return self.orders

    def get_deals(self):
        if self.deals_error:
            raise RuntimeError(self.deals_error)
        return self.deals


def futu_position(symbol="US.EMR", qty=100, cost=100):
    return {
        "code": symbol,
        "qty": qty,
        "cost_price": cost,
        "market_val": qty * cost,
        "pl_ratio": 0,
    }


def test_remote_position_without_local_issue_blocks_new_entries(session):
    result = run_trade_reconciliation(
        session,
        ReconcileProvider(positions=[futu_position()]),
        Settings(),
    )

    issue = session.query(ReconciliationIssue).one()
    assert issue.issue_type == "REMOTE_POSITION_WITHOUT_LOCAL"
    assert issue.severity == "HIGH"
    assert result["allow_new_entries"] is False


def test_local_position_missing_remote_issue(session):
    session.add(
        Position(
            symbol="US.EMR",
            status="OPEN",
            entry_price=100,
            stop_price=95,
            shares=100,
            available_shares=100,
            risk_amount=500,
            source="LOCAL_STRATEGY",
        )
    )
    session.commit()

    run_trade_reconciliation(session, ReconcileProvider(), Settings())

    issue = session.query(ReconciliationIssue).one()
    assert issue.issue_type == "LOCAL_POSITION_MISSING_REMOTE"
    assert issue.severity == "HIGH"


def test_position_qty_mismatch_issue(session):
    session.add(
        Position(
            symbol="US.EMR",
            status="OPEN",
            entry_price=100,
            stop_price=95,
            shares=100,
            available_shares=100,
            risk_amount=500,
            source="LOCAL_STRATEGY",
        )
    )
    session.commit()

    run_trade_reconciliation(session, ReconcileProvider(positions=[futu_position(qty=80)]), Settings())

    issue = session.query(ReconciliationIssue).filter_by(issue_type="POSITION_QTY_MISMATCH").one()
    assert issue.severity == "HIGH"


def test_position_cost_mismatch_issue(session):
    session.add(
        Position(
            symbol="US.EMR",
            status="OPEN",
            entry_price=100,
            stop_price=95,
            shares=100,
            available_shares=100,
            risk_amount=500,
            source="LOCAL_STRATEGY",
        )
    )
    session.commit()

    run_trade_reconciliation(session, ReconcileProvider(positions=[futu_position(cost=104)]), Settings())

    issue = session.query(ReconciliationIssue).filter_by(issue_type="POSITION_COST_MISMATCH").one()
    assert issue.severity == "WARN"


def test_sell_order_stuck_issue(session):
    session.add(
        SimOrder(
            symbol="US.EMR",
            side="SELL",
            qty=100,
            limit_price=99,
            futu_order_id="sell-1",
            status="SELL_WAITING_RECONCILIATION",
            reason="HARD_STOP",
        )
    )
    session.commit()

    run_trade_reconciliation(session, ReconcileProvider(), Settings())

    issue = session.query(ReconciliationIssue).one()
    assert issue.issue_type == "SELL_ORDER_STUCK"
    assert issue.severity == "HIGH"


def test_closed_unverified_issue(session):
    session.add(
        Position(
            symbol="US.EMR",
            status="CLOSED_UNVERIFIED",
            entry_price=100,
            stop_price=95,
            shares=0,
            available_shares=0,
            risk_amount=500,
            source="FUTU_DETECTED",
            close_verified=False,
        )
    )
    session.commit()

    run_trade_reconciliation(session, ReconcileProvider(), Settings())

    issue = session.query(ReconciliationIssue).one()
    assert issue.issue_type == "CLOSE_UNVERIFIED"
    assert issue.severity == "WARN"


def test_issue_upsert_does_not_duplicate_open_issue(session):
    provider = ReconcileProvider(positions=[futu_position()])

    run_trade_reconciliation(session, provider, Settings())
    issue = session.query(ReconciliationIssue).one()
    issue.last_seen_at = datetime.utcnow() - timedelta(minutes=10)
    session.commit()
    previous_id = issue.id

    run_trade_reconciliation(session, provider, Settings())

    issues = session.query(ReconciliationIssue).all()
    assert len(issues) == 1
    assert issues[0].id == previous_id
    assert issues[0].last_seen_at > issue.first_seen_at


def test_issue_auto_resolves_when_problem_disappears(session):
    run_trade_reconciliation(session, ReconcileProvider(positions=[futu_position()]), Settings())
    issue = session.query(ReconciliationIssue).one()

    session.add(
        Position(
            symbol="US.EMR",
            status="OPEN",
            entry_price=100,
            stop_price=95,
            shares=100,
            available_shares=100,
            risk_amount=500,
            source="LOCAL_STRATEGY",
        )
    )
    session.commit()
    run_trade_reconciliation(session, ReconcileProvider(positions=[futu_position()]), Settings())

    assert issue.status == "RESOLVED"
    assert issue.resolved_at is not None


def test_sim_loop_returns_reconciliation_payload(session):
    result = run_sim_loop(session, Settings(), use_mock=True)

    assert "reconciliation" in result
    assert "allow_new_entries" in result["reconciliation"]
    record = session.query(SystemConfig).filter_by(key="reconciliation_gate_status").one()
    assert "allow_new_entries" in record.value
    summary = terminal_summary(session, Settings())
    assert summary["reconciliation"]["mode"] == "NORMAL"
    assert summary["reconciliation"]["allow_new_entries"] is True


class QuoteProvider:
    def get_market_snapshot(self, symbols):
        return [{"code": symbol, "last_price": 94, "bid_price": 93.8} for symbol in symbols]


class SellProvider(ReconcileProvider):
    def __init__(self):
        super().__init__()
        self.orders = []

    def place_simulated_order(self, symbol, side, quantity, price):
        self.orders.append((symbol, side, quantity, price))
        return {"order_id": "sell-1"}


def test_high_reconciliation_issue_does_not_block_existing_position_sell(session):
    session.add_all(
        [
            ReconciliationIssue(issue_type="LOCAL_POSITION_MISSING_REMOTE", severity="HIGH", status="OPEN", reason="对账异常"),
            Position(
                symbol="US.EMR",
                status="OPEN",
                entry_price=100,
                stop_price=95,
                shares=100,
                available_shares=100,
                current_price=94,
                risk_amount=500,
                source="LOCAL_STRATEGY",
            ),
        ]
    )
    session.commit()
    provider = SellProvider()

    result = manage_positions(session, QuoteProvider(), provider, Settings(force_intraday_exit=False))

    assert result["exit_orders_submitted"] == 1
    assert provider.orders == [("US.EMR", "SELL", 100, 93.8)]


def test_run_sim_loop_enters_protective_mode_when_reconciliation_sync_fails(session, monkeypatch):
    class BrokenTradeProvider:
        def close(self):
            pass

        def get_open_orders(self):
            return []

        def get_deals(self):
            return []

        def get_positions(self):
            raise RuntimeError("positions unavailable")

        def get_account_info(self):
            return {"cash": 100000, "total_assets": 100000}

    monkeypatch.setattr("app.services.sim_loop.MockTradeProvider", BrokenTradeProvider)

    result = run_sim_loop(session, Settings(), use_mock=True)
    summary = terminal_summary(session, Settings())

    assert result["reconciliation"]["allow_new_entries"] is False
    assert result["reconciliation"]["mode"] in {"SYNC_FAILED", "PROTECTIVE"}
    assert summary["reconciliation"]["allow_new_entries"] is False
    assert summary["reconciliation"]["mode"] in {"SYNC_FAILED", "PROTECTIVE"}
