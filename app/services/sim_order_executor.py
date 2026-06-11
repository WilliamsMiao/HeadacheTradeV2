import json
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import AuditLog, Indicator, SimOrder, TradePlan
from app.services.audit import write_audit


def execute_approved_sim_orders(session: Session, trade_provider, settings: Settings) -> dict[str, int]:
    settings.assert_simulation_only()
    if not settings.enable_sim_trading:
        return {"submitted": 0, "failed": 0}
    plans = list(
        session.scalars(
            select(TradePlan)
            .where(
                TradePlan.status == "TRIGGERED",
                TradePlan.rules_approval_status == "APPROVED_FOR_SIM_TRADE",
                TradePlan.direction == "LONG",
            )
            .order_by(TradePlan.last_validated_at.asc(), TradePlan.id.asc())
        )
    )
    submitted = failed = 0
    for plan in plans:
        if session.scalar(
            select(SimOrder).where(
                SimOrder.symbol == plan.symbol,
                SimOrder.status.in_({"SUBMITTED", "PARTIALLY_FILLED"}),
            )
        ):
            continue
        qty = int(plan.suggested_shares or 0)
        if qty <= 0:
            risk_per_share = float(plan.breakout_entry_price or 0) - plan.stop_price
            risk_budget = settings.risk_per_trade_pct * float(plan.available_cash_snapshot or 100_000)
            qty = int(risk_budget // risk_per_share) if risk_per_share > 0 else 0
        if qty <= 0:
            plan.status = "BLOCKED"
            plan.rules_reject_reason = "风险预算不足以购买 1 股"
            failed += 1
            continue
        current = float(plan.current_price or plan.breakout_entry_price or 0)
        limit_price = min(
            current,
            float(plan.no_chase_above or current),
        )
        order = SimOrder(
            trade_plan_id=plan.id,
            symbol=plan.symbol,
            side="BUY",
            qty=qty,
            limit_price=round(limit_price, 2),
            submitted_price=current,
            trd_env="SIMULATE",
            status="SUBMITTED",
            reason="First Valid Trade rules approval",
        )
        session.add(order)
        session.flush()
        try:
            response = trade_provider.place_simulated_order(plan.symbol, "BUY", qty, limit_price)
            order.futu_order_id = str(response.get("order_id") or "")
            order.raw_response_json = json.dumps(response, ensure_ascii=False, default=str)
            plan.status = "ORDER_SUBMITTED"
            plan.simulated_order_id = order.id
            submitted += 1
            write_audit(
                session,
                "SIM_ORDER_SUBMITTED",
                symbol=plan.symbol,
                subject_type="SimOrder",
                subject_id=order.id,
                status="SUBMITTED",
                payload={"qty": qty, "limit_price": limit_price, "response": response},
            )
        except Exception as exc:
            order.status = "FAILED"
            order.reason = str(exc)
            plan.status = "BLOCKED"
            plan.rules_reject_reason = str(exc)
            failed += 1
            write_audit(
                session,
                "SIM_ORDER_FAILED",
                symbol=plan.symbol,
                subject_type="SimOrder",
                subject_id=order.id,
                status="FAILED",
                reason=str(exc),
            )
        session.commit()
        if submitted:
            break
    return {"submitted": submitted, "failed": failed}
