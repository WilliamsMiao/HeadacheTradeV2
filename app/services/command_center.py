from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import AuditLog, BattlePoolItem, CandidateStock, Position, SimOrder, StructureEvent, TradePlan
from app.presentation_status import status_for
from app.services.next_action import describe_position_next_action, describe_trade_plan_next_action


EXECUTABLE = {"ACTIVE", "PLANNED", "ARMED", "TRIGGERED", "ORDER_SUBMITTED"}
BLOCKED = {"NO_CHASE", "WAITLIST", "MISSED_BY_CAPITAL", "BLOCKED", "PAUSED", "INVALIDATED", "EXPIRED"}


def command_center_payload(session: Session, settings: Settings) -> dict:
    plans = list(session.scalars(select(TradePlan).order_by(TradePlan.updated_at.desc())))
    positions = list(session.scalars(select(Position).where(Position.status == "OPEN").order_by(Position.updated_at.desc())))
    executable = [_plan_view(plan) for plan in plans if plan.priority_level in {"S", "A"} and plan.status in EXECUTABLE]
    blocked = [_plan_view(plan) for plan in plans if plan.status in BLOCKED or plan.rules_approval_status.startswith("REJECTED")]
    logs = list(session.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(20)))
    funnel = {
        "候选池": session.scalar(select(func.count(CandidateStock.id)).where(CandidateStock.active.is_(True))) or 0,
        "60m 结构": session.scalar(select(func.count(func.distinct(StructureEvent.symbol))).where(StructureEvent.timeframe == "60m")) or 0,
        "作战池": session.scalar(select(func.count(BattlePoolItem.id)).where(BattlePoolItem.status == "ACTIVE")) or 0,
        "S/A 级": session.scalar(select(func.count(BattlePoolItem.id)).where(BattlePoolItem.status == "ACTIVE", BattlePoolItem.priority_level.in_({"S", "A"}))) or 0,
        "交易计划": sum(plan.status not in {"INVALIDATED", "EXPIRED"} for plan in plans),
        "实时校验": sum(plan.last_validated_at is not None for plan in plans),
        "规则通过": sum(plan.rules_approval_status == "APPROVED_FOR_SIM_TRADE" for plan in plans),
        "模拟订单": session.scalar(select(func.count(SimOrder.id))) or 0,
        "当前持仓": len(positions),
    }
    today_orders = session.scalar(
        select(func.count(SimOrder.id)).where(
            func.date(SimOrder.submitted_at) == datetime.utcnow().date().isoformat(),
            SimOrder.side == "BUY",
        )
    ) or 0
    return {
        "system": {
            "sim_mode": "运行中" if settings.enable_sim_trading else "已停止",
            "sim_severity": "success" if settings.enable_sim_trading else "danger",
            "real_trading": "永久禁用",
            "new_trades": today_orders,
            "max_new_trades": settings.max_daily_new_trades,
            "positions": len(positions),
            "max_positions": settings.max_positions,
            "allows_entry": settings.enable_sim_trading and today_orders < settings.max_daily_new_trades,
            "stop_reason": "" if settings.enable_sim_trading else "模拟交易总开关关闭",
        },
        "positions_vm": [
            {"record": position, "next_action": describe_position_next_action(position)}
            for position in positions
        ],
        "executable": executable[:6],
        "blocked": blocked[:8],
        "funnel": funnel,
        "timeline": logs,
    }


def _plan_view(plan: TradePlan) -> dict:
    status = status_for(plan.status)
    return {
        "record": plan,
        "status": status,
        "next_action": describe_trade_plan_next_action(plan),
        "reason": plan.rules_reject_reason or plan.capital_reason or plan.reason,
    }
