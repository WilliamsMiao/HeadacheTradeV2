from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import AuditLog, BattlePoolItem, CandidateStock, Position, SimOrder, StructureEvent, TradePlan, TradingState
from app.presentation_status import status_for
from app.services.command_center import plan_view_model
from app.services.next_action import (
    describe_battle_next_action,
    describe_candidate_next_action,
    describe_position_next_action,
    describe_trade_plan_next_action,
)


def candidate_view_models(session: Session, candidates: list[CandidateStock]) -> list[dict]:
    output = []
    for rank, candidate in enumerate(candidates, start=1):
        structure = session.scalar(select(StructureEvent).where(StructureEvent.symbol == candidate.symbol).order_by(StructureEvent.event_ts.desc()).limit(1))
        battle = session.scalar(select(BattlePoolItem).where(BattlePoolItem.symbol == candidate.symbol, BattlePoolItem.status == "ACTIVE"))
        plan = session.scalar(select(TradePlan).where(TradePlan.symbol == candidate.symbol).order_by(TradePlan.updated_at.desc()).limit(1))
        position = session.scalar(select(Position).where(Position.symbol == candidate.symbol, Position.status == "OPEN"))
        state = session.scalar(select(TradingState).where(TradingState.symbol == candidate.symbol))
        if position:
            funnel_status, reason = "IN_POSITION", "已有模拟持仓，系统优先管理止损和目标。"
        elif state and state.state == "COOLDOWN":
            funnel_status, reason = "COOLDOWN", state.last_reason
        elif plan and plan.status not in {"INVALIDATED", "EXPIRED"}:
            funnel_status, reason = "ACTIVE_PLAN", f"已生成 {plan.priority_level} 级交易计划。"
        elif battle:
            funnel_status = "BATTLE_BUT_NOT_SA" if battle.priority_level not in {"S", "A"} else "PLAN_BLOCKED"
            reason = battle.reason
        elif structure and structure.event_type.endswith("PASSIVATION"):
            funnel_status, reason = "WAIT_CONFIRM", structure.reason
        elif structure:
            funnel_status, reason = "STOP_TOO_WIDE", "已有结构，但尚未通过作战评分或止损距离要求。"
        elif candidate.candidate_status == "DROPPED":
            funnel_status, reason = "DROPPED", candidate.dropped_reason
        else:
            funnel_status, reason = "NO_STRUCTURE", "成交与标签符合观察条件，但暂无可作战的 60 分钟结构。"
        output.append({
            "record": candidate,
            "rank": rank,
            "funnel_status": funnel_status,
            "reason": reason,
            "next_action": describe_candidate_next_action(funnel_status),
            "structure": structure,
            "battle": battle,
            "plan": plan,
        })
    return output


def battle_view_models(session: Session, items: list[BattlePoolItem]) -> list[dict]:
    output = []
    for item in items:
        plan = session.scalar(select(TradePlan).where(TradePlan.symbol == item.symbol).order_by(TradePlan.updated_at.desc()).limit(1))
        breakdown = []
        for part in (item.reason or "").split("；"):
            if "贡献" in part or "扣" in part:
                breakdown.append(part)
        output.append({
            "record": item,
            "plan": plan,
            "breakdown": breakdown,
            "next_action": describe_battle_next_action(item, bool(plan)),
        })
    return output


def trade_plan_groups(session: Session, plans: list[TradePlan], settings: Settings) -> list[dict]:
    groups = [
        ("待触发计划", {"ACTIVE", "PLANNED", "ARMED"}),
        ("已触发待处理", {"TRIGGERED", "ORDER_SUBMITTED"}),
        ("持仓中", {"IN_POSITION"}),
        ("等待回踩", {"WAIT_PULLBACK"}),
        ("执行阻塞", {"WAITLIST", "MISSED_BY_CAPITAL", "NO_CHASE", "BLOCKED", "PAUSED"}),
        ("失效计划", {"INVALIDATED", "EXPIRED"}),
    ]
    result = []
    for title, statuses in groups:
        items = [trade_plan_view_model(session, plan, settings) for plan in plans if plan.status in statuses]
        if items:
            result.append({"title": title, "items": items})
    return result


def trade_plan_view_model(session: Session, plan: TradePlan, settings: Settings) -> dict:
    item = plan_view_model(session, plan, settings)
    item.update(_journey_for_plan(session, plan))
    item["orders"] = list(
        session.scalars(select(SimOrder).where(SimOrder.trade_plan_id == plan.id).order_by(SimOrder.submitted_at.desc()))
    )
    item["position"] = session.scalar(
        select(Position).where(Position.source_trade_plan_id == plan.id).order_by(Position.updated_at.desc()).limit(1)
    )
    item["validation_logs"] = list(
        session.scalars(
            select(AuditLog)
            .where(AuditLog.subject_type == "TradePlan", AuditLog.subject_id == plan.id)
            .order_by(AuditLog.created_at.desc())
            .limit(8)
        )
    )
    return item


def structure_view_models(session: Session, events: list[StructureEvent]) -> list[dict]:
    output = []
    for event in events:
        battle = session.scalar(select(BattlePoolItem).where(BattlePoolItem.source_structure_id == event.id))
        plan = session.scalar(
            select(TradePlan).where(TradePlan.source_structure_id == event.id).order_by(TradePlan.updated_at.desc()).limit(1)
        )
        output.append({"record": event, "battle": battle, "plan": plan})
    return output


def journal_view_models(session: Session) -> list[dict]:
    plans = list(
        session.scalars(
            select(TradePlan)
            .where(
                (TradePlan.id.in_(select(Position.source_trade_plan_id).where(Position.source_trade_plan_id.is_not(None))))
                | (
                    TradePlan.id.in_(
                        select(SimOrder.trade_plan_id).where(
                            SimOrder.trade_plan_id.is_not(None),
                            (SimOrder.dealt_qty > 0) | SimOrder.status.in_({"FILLED", "PARTIALLY_FILLED"}),
                        )
                    )
                )
            )
            .order_by(TradePlan.updated_at.desc())
            .limit(100)
        )
    )
    output = []
    for plan in plans:
        orders = list(
            session.scalars(select(SimOrder).where(SimOrder.trade_plan_id == plan.id).order_by(SimOrder.submitted_at))
        )
        position = session.scalar(
            select(Position).where(Position.source_trade_plan_id == plan.id).order_by(Position.updated_at.desc()).limit(1)
        )
        logs = list(
            session.scalars(
                select(AuditLog)
                .where(AuditLog.symbol == plan.symbol)
                .order_by(AuditLog.created_at.desc())
                .limit(12)
            )
        )
        output.append(
            {
                "plan": plan,
                "orders": orders,
                "position": position,
                "logs": logs,
                "outcome": _journal_outcome(plan, position, orders),
                **_journey_for_plan(session, plan),
            }
        )
    return output


def _journey_for_plan(session: Session, plan: TradePlan) -> dict:
    candidate = session.scalar(select(CandidateStock).where(CandidateStock.symbol == plan.symbol))
    structure = session.get(StructureEvent, plan.source_structure_id)
    battle = session.get(BattlePoolItem, plan.battle_pool_id)
    order = session.scalar(
        select(SimOrder).where(SimOrder.trade_plan_id == plan.id).order_by(SimOrder.submitted_at.desc()).limit(1)
    )
    position = session.scalar(
        select(Position).where(Position.source_trade_plan_id == plan.id).order_by(Position.updated_at.desc()).limit(1)
    )
    current = "position" if position else "order" if order else "plan"
    return {
        "journey": {
            "candidate": candidate,
            "structure": structure,
            "battle": battle,
            "plan": plan,
            "order": order,
            "position": position,
            "current": current,
        }
    }


def _journal_outcome(plan: TradePlan, position: Position | None, orders: list[SimOrder]) -> str:
    if position and position.status == "OPEN":
        return f"持仓中，当前 {position.current_r:.2f}R"
    if position:
        return position.exit_reason or f"持仓已结束，最终 {position.current_r:.2f}R"
    if orders:
        return f"最近订单：{status_for(orders[-1].status).display_name}"
    if plan.status in {"INVALIDATED", "EXPIRED"}:
        return "计划失效，未形成持仓"
    return "计划仍在观察或等待执行"


def position_view_models(session: Session, positions: list[Position]) -> list[dict]:
    output = []
    for position in positions:
        plan = session.get(TradePlan, position.source_trade_plan_id) if position.source_trade_plan_id else None
        latest_audit = session.scalar(
            select(AuditLog)
            .where(
                AuditLog.subject_type == "Position",
                AuditLog.subject_id == position.id,
            )
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        )
        current_price = float(position.current_price or 0)
        effective_stop = max(float(position.stop_price or 0), float(position.trailing_stop_price or 0))
        output.append({
            "record": position,
            "plan": plan,
            "latest_audit": latest_audit,
            "take_profit_reached": bool(position.target_1 and current_price >= position.target_1),
            "stop_loss_reached": bool(effective_stop and current_price <= effective_stop),
            "next_action": describe_position_next_action(position),
        })
    return output


def order_view_models(session: Session, orders: list[SimOrder]) -> list[dict]:
    output = []
    for order in orders:
        plan = session.get(TradePlan, order.trade_plan_id) if order.trade_plan_id else None
        output.append({"record": order, "plan": plan, "status": status_for(order.status)})
    return output
