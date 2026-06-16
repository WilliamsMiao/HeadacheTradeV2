from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import TradePlan
from app.providers.futu_provider import FutuProvider
from app.providers.futu_trade_provider import FutuTradeProvider
from app.providers.mock_provider import MockProvider
from app.providers.mock_trade_provider import MockTradeProvider
from app.services.order_sync import sync_sim_orders
from app.services.portfolio_manager import get_portfolio_state, rank_waitlisted_plans
from app.services.position_manager import manage_positions
from app.services.position_sync import sync_futu_positions_to_local
from app.services.realtime_execution_validator import validate_active_trade_plans
from app.services.rules_approval import rules_approve_trade_plan
from app.services.sim_order_executor import execute_approved_sim_orders
from app.services.trade_reconciler import (
    run_trade_reconciliation,
    save_reconciliation_gate_failure,
    save_reconciliation_gate_status,
)


def run_sim_loop(session: Session, settings: Settings, use_mock: bool = False) -> dict[str, object]:
    settings.assert_simulation_only()
    quote_provider = MockProvider([]) if use_mock else FutuProvider(settings)
    trade_provider = MockTradeProvider() if use_mock else FutuTradeProvider(settings)
    try:
        synced = sync_sim_orders(session, trade_provider, settings.entry_order_timeout_seconds)
        try:
            position_sync = sync_futu_positions_to_local(session, trade_provider, settings)
        except Exception as exc:
            position_sync = {"remote": 0, "created": 0, "updated": 0, "closed": 0, "error": str(exc)}
        try:
            reconciliation = run_trade_reconciliation(session, trade_provider, settings)
            save_reconciliation_gate_status(session, reconciliation)
        except Exception as exc:
            gate = save_reconciliation_gate_failure(session, f"交易对账运行失败：{exc}")
            reconciliation = {
                "ok": False,
                "severity": gate["severity"],
                "issues_opened": 1,
                "issues_resolved": 0,
                "open_issues": gate["open_issues"],
                "critical_issues": gate["critical_issues"],
                "high_issues": gate["high_issues"],
                "allow_new_entries": False,
                "reason": gate["reason"],
                "mode": gate["mode"],
            }
        managed = manage_positions(session, quote_provider, trade_provider, settings)
        portfolio = get_portfolio_state(session, trade_provider, settings)
        validation = validate_active_trade_plans(session, quote_provider, settings)
        decisions = {"approved": 0, "rejected": 0}
        contexts = validation.pop("contexts")
        triggered = list(
            session.scalars(
                select(TradePlan)
                .where(TradePlan.status == "TRIGGERED")
                .order_by(TradePlan.last_validated_at.asc(), TradePlan.id.asc())
            )
        )
        for plan in triggered:
            plan.available_cash_snapshot = portfolio.available_cash
            plan.max_new_position_value = portfolio.account_equity * settings.max_symbol_position_pct
            decision = rules_approve_trade_plan(
                session,
                plan,
                contexts.get(plan.id, {}),
                portfolio,
                settings,
            )
            decisions["approved" if decision.approved else "rejected"] += 1
            if decision.approved:
                break
        executed = execute_approved_sim_orders(session, trade_provider, settings)
        waitlist = rank_waitlisted_plans(session)
        return {
            "synced": synced,
            "position_sync": position_sync,
            "reconciliation": reconciliation,
            "positions": managed,
            "portfolio": portfolio.__dict__,
            "validation": validation,
            "approval": decisions,
            "orders": executed,
            "waitlist": len(waitlist),
        }
    finally:
        quote_provider.close()
        trade_provider.close()
