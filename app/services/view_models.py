import json
from collections import defaultdict

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
    symbols = [candidate.symbol for candidate in candidates]
    latest_structures_by_symbol = _latest_by_symbol(
        session.scalars(
            select(StructureEvent)
            .where(StructureEvent.symbol.in_(symbols))
            .order_by(StructureEvent.symbol, StructureEvent.event_ts.desc(), StructureEvent.id.desc())
        )
        if symbols
        else []
    )
    battle_by_symbol = {
        item.symbol: item
        for item in session.scalars(
            select(BattlePoolItem).where(BattlePoolItem.symbol.in_(symbols), BattlePoolItem.status == "ACTIVE")
        )
    } if symbols else {}
    latest_plan_by_symbol = _latest_by_symbol(
        session.scalars(
            select(TradePlan)
            .where(TradePlan.symbol.in_(symbols))
            .order_by(TradePlan.symbol, TradePlan.updated_at.desc(), TradePlan.id.desc())
        )
        if symbols
        else []
    )
    open_position_by_symbol = {
        position.symbol: position
        for position in session.scalars(select(Position).where(Position.symbol.in_(symbols), Position.status == "OPEN"))
    } if symbols else {}
    state_by_symbol = {
        state.symbol: state
        for state in session.scalars(select(TradingState).where(TradingState.symbol.in_(symbols)))
    } if symbols else {}
    output = []
    for rank, candidate in enumerate(candidates, start=1):
        structure = latest_structures_by_symbol.get(candidate.symbol)
        battle = battle_by_symbol.get(candidate.symbol)
        plan = latest_plan_by_symbol.get(candidate.symbol)
        position = open_position_by_symbol.get(candidate.symbol)
        state = state_by_symbol.get(candidate.symbol)
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
    symbols = [item.symbol for item in items]
    plans_by_symbol = _latest_by_symbol(
        session.scalars(
            select(TradePlan)
            .where(TradePlan.symbol.in_(symbols))
            .order_by(TradePlan.symbol, TradePlan.updated_at.desc(), TradePlan.id.desc())
        )
        if symbols
        else []
    )
    output = []
    for item in items:
        plan = plans_by_symbol.get(item.symbol)
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
    context = _trade_plan_batch_context(session, plans)
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
        items = [trade_plan_view_model(session, plan, settings, context=context) for plan in plans if plan.status in statuses]
        if items:
            result.append({"title": title, "items": items})
    return result


def trade_plan_view_model(session: Session, plan: TradePlan, settings: Settings, context: dict | None = None) -> dict:
    context = context or _trade_plan_batch_context(session, [plan])
    item = plan_view_model(
        session,
        plan,
        settings,
        validation=context["latest_validation_by_plan_id"].get(plan.id, {}),
        has_position=plan.symbol in context["open_position_symbols"],
        has_order=plan.symbol in context["pending_order_symbols"],
        portfolio_sync=context["portfolio_sync"],
    )
    item.update(_journey_for_plan(session, plan, context=context))
    item["orders"] = context["orders_by_plan_id"].get(plan.id, [])
    item["position"] = context["positions_by_plan_id"].get(plan.id)
    item["validation_logs"] = context["audit_logs_by_plan_id"].get(plan.id, [])[:8]
    return item


def structure_view_models(session: Session, events: list[StructureEvent]) -> list[dict]:
    structure_ids = [event.id for event in events]
    battles = list(session.scalars(select(BattlePoolItem).where(BattlePoolItem.source_structure_id.in_(structure_ids)))) if structure_ids else []
    battle_by_structure_id = {battle.source_structure_id: battle for battle in battles}
    plans_by_structure_id = _latest_by_key(
        session.scalars(
            select(TradePlan)
            .where(TradePlan.source_structure_id.in_(structure_ids))
            .order_by(TradePlan.source_structure_id, TradePlan.updated_at.desc(), TradePlan.id.desc())
        )
        if structure_ids
        else [],
        "source_structure_id",
    )
    output = []
    for event in events:
        battle = battle_by_structure_id.get(event.id)
        plan = plans_by_structure_id.get(event.id)
        output.append({"record": event, "battle": battle, "plan": plan})
    return output


def journal_view_models(session: Session, limit: int = 50) -> list[dict]:
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
            .limit(max(1, min(limit, 100)))
        )
    )
    context = _trade_plan_batch_context(session, plans, audit_symbol_limit=12)
    output = []
    for plan in plans:
        orders = list(reversed(context["orders_by_plan_id"].get(plan.id, [])))
        position = context["positions_by_plan_id"].get(plan.id)
        logs = context["audit_logs_by_symbol"].get(plan.symbol, [])[:12]
        output.append(
            {
                "plan": plan,
                "orders": orders,
                "position": position,
                "logs": logs,
                "outcome": _journal_outcome(plan, position, orders),
                **_journey_for_plan(session, plan, context=context),
            }
        )
    return output


def _journey_for_plan(session: Session, plan: TradePlan, context: dict | None = None) -> dict:
    context = context or _trade_plan_batch_context(session, [plan])
    candidate = context["candidates_by_symbol"].get(plan.symbol)
    structure = context["structures_by_id"].get(plan.source_structure_id)
    battle = context["battles_by_id"].get(plan.battle_pool_id)
    order = context["latest_order_by_plan_id"].get(plan.id)
    position = context["positions_by_plan_id"].get(plan.id)
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
    plan_ids = [position.source_trade_plan_id for position in positions if position.source_trade_plan_id]
    plans_by_id = {plan.id: plan for plan in session.scalars(select(TradePlan).where(TradePlan.id.in_(plan_ids)))} if plan_ids else {}
    latest_audit_by_position_id = _latest_audits_by_subject(session, "Position", [position.id for position in positions])
    output = []
    for position in positions:
        plan = plans_by_id.get(position.source_trade_plan_id) if position.source_trade_plan_id else None
        latest_audit = latest_audit_by_position_id.get(position.id)
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
    plan_ids = [order.trade_plan_id for order in orders if order.trade_plan_id]
    plans_by_id = {plan.id: plan for plan in session.scalars(select(TradePlan).where(TradePlan.id.in_(plan_ids)))} if plan_ids else {}
    output = []
    for order in orders:
        plan = plans_by_id.get(order.trade_plan_id) if order.trade_plan_id else None
        output.append({"record": order, "plan": plan, "status": status_for(order.status)})
    return output


def _trade_plan_batch_context(session: Session, plans: list[TradePlan], audit_symbol_limit: int = 0) -> dict:
    from app.services.command_center import _latest_validation
    from app.services.portfolio_manager import portfolio_sync_status

    plan_ids = [plan.id for plan in plans]
    symbols = sorted({plan.symbol for plan in plans})
    source_structure_ids = [plan.source_structure_id for plan in plans if plan.source_structure_id]
    battle_ids = [plan.battle_pool_id for plan in plans if plan.battle_pool_id]
    orders_by_plan_id = defaultdict(list)
    latest_order_by_plan_id = {}
    for order in session.scalars(
        select(SimOrder)
        .where(SimOrder.trade_plan_id.in_(plan_ids))
        .order_by(SimOrder.trade_plan_id, SimOrder.submitted_at.desc(), SimOrder.id.desc())
    ) if plan_ids else []:
        orders_by_plan_id[order.trade_plan_id].append(order)
        latest_order_by_plan_id.setdefault(order.trade_plan_id, order)

    positions_by_plan_id = _latest_by_key(
        session.scalars(
            select(Position)
            .where(Position.source_trade_plan_id.in_(plan_ids))
            .order_by(Position.source_trade_plan_id, Position.updated_at.desc(), Position.id.desc())
        )
        if plan_ids
        else [],
        "source_trade_plan_id",
    )
    audit_logs_by_plan_id = defaultdict(list)
    latest_validation_by_plan_id = {}
    for log in session.scalars(
        select(AuditLog)
        .where(AuditLog.subject_type == "TradePlan", AuditLog.subject_id.in_(plan_ids))
        .order_by(AuditLog.subject_id, AuditLog.created_at.desc(), AuditLog.id.desc())
    ) if plan_ids else []:
        logs = audit_logs_by_plan_id[log.subject_id]
        if len(logs) < 8:
            logs.append(log)
        if log.action == "TRADE_PLAN_VALIDATED" and log.subject_id not in latest_validation_by_plan_id:
            latest_validation_by_plan_id[log.subject_id] = _parse_validation_log(log)
    for plan in plans:
        latest_validation_by_plan_id.setdefault(plan.id, {})

    audit_logs_by_symbol = defaultdict(list)
    if audit_symbol_limit and symbols:
        for log in session.scalars(
            select(AuditLog)
            .where(AuditLog.symbol.in_(symbols))
            .order_by(AuditLog.symbol, AuditLog.created_at.desc(), AuditLog.id.desc())
        ):
            logs = audit_logs_by_symbol[log.symbol]
            if len(logs) < audit_symbol_limit:
                logs.append(log)

    pending_order_symbols = {
        order.symbol
        for order in session.scalars(
            select(SimOrder).where(SimOrder.symbol.in_(symbols), SimOrder.status.in_({"SUBMITTED", "PARTIALLY_FILLED"}))
        )
    } if symbols else set()
    open_position_symbols = {
        position.symbol
        for position in session.scalars(select(Position).where(Position.symbol.in_(symbols), Position.status == "OPEN"))
    } if symbols else set()
    return {
        "orders_by_plan_id": dict(orders_by_plan_id),
        "latest_order_by_plan_id": latest_order_by_plan_id,
        "positions_by_plan_id": positions_by_plan_id,
        "audit_logs_by_plan_id": dict(audit_logs_by_plan_id),
        "audit_logs_by_symbol": dict(audit_logs_by_symbol),
        "latest_validation_by_plan_id": latest_validation_by_plan_id,
        "candidates_by_symbol": {
            candidate.symbol: candidate
            for candidate in session.scalars(select(CandidateStock).where(CandidateStock.symbol.in_(symbols)))
        } if symbols else {},
        "structures_by_id": {
            structure.id: structure
            for structure in session.scalars(select(StructureEvent).where(StructureEvent.id.in_(source_structure_ids)))
        } if source_structure_ids else {},
        "battles_by_id": {
            battle.id: battle
            for battle in session.scalars(select(BattlePoolItem).where(BattlePoolItem.id.in_(battle_ids)))
        } if battle_ids else {},
        "pending_order_symbols": pending_order_symbols,
        "open_position_symbols": open_position_symbols,
        "portfolio_sync": portfolio_sync_status(session),
    }


def _parse_validation_log(log: AuditLog) -> dict:
    from datetime import UTC, datetime

    try:
        payload = json.loads(log.payload_json or "{}")
    except json.JSONDecodeError:
        return {}
    payload["_is_fresh"] = (datetime.now(UTC).replace(tzinfo=None) - log.created_at).total_seconds() <= 120
    return payload


def _latest_by_symbol(rows) -> dict:
    return _latest_by_key(rows, "symbol")


def _latest_by_key(rows, key_name: str) -> dict:
    output = {}
    for row in rows:
        output.setdefault(getattr(row, key_name), row)
    return output


def _latest_audits_by_subject(session: Session, subject_type: str, subject_ids: list[int]) -> dict[int, AuditLog]:
    return _latest_by_key(
        session.scalars(
            select(AuditLog)
            .where(AuditLog.subject_type == subject_type, AuditLog.subject_id.in_(subject_ids))
            .order_by(AuditLog.subject_id, AuditLog.created_at.desc(), AuditLog.id.desc())
        )
        if subject_ids
        else [],
        "subject_id",
    )
