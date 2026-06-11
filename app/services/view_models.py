from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BattlePoolItem, CandidateStock, Position, SimOrder, StructureEvent, TradePlan, TradingState
from app.presentation_status import status_for
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


def trade_plan_groups(plans: list[TradePlan]) -> list[dict]:
    groups = [
        ("可执行机会", {"ACTIVE", "PLANNED", "ARMED"}),
        ("已触发", {"TRIGGERED", "ORDER_SUBMITTED"}),
        ("已持仓", {"IN_POSITION"}),
        ("等待回踩", {"WAIT_PULLBACK"}),
        ("资金不足", {"WAITLIST", "MISSED_BY_CAPITAL"}),
        ("禁止追价", {"NO_CHASE"}),
        ("已拒绝", {"BLOCKED", "PAUSED"}),
        ("已失效", {"INVALIDATED", "EXPIRED"}),
    ]
    result = []
    for title, statuses in groups:
        items = [
            {"record": plan, "status": status_for(plan.status), "next_action": describe_trade_plan_next_action(plan)}
            for plan in plans if plan.status in statuses
        ]
        if items:
            result.append({"title": title, "items": items})
    return result


def position_view_models(session: Session, positions: list[Position]) -> list[dict]:
    output = []
    for position in positions:
        plan = session.get(TradePlan, position.source_trade_plan_id) if position.source_trade_plan_id else None
        output.append({
            "record": position,
            "plan": plan,
            "next_action": describe_position_next_action(position),
        })
    return output


def order_view_models(session: Session, orders: list[SimOrder]) -> list[dict]:
    output = []
    for order in orders:
        plan = session.get(TradePlan, order.trade_plan_id) if order.trade_plan_id else None
        output.append({"record": order, "plan": plan, "status": status_for(order.status)})
    return output
