import json
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import AuditLog, BattlePoolItem, CandidateStock, Position, SimOrder, StructureEvent, TradePlan
from app.presentation_status import status_for
from app.services.next_action import describe_position_next_action, describe_trade_plan_next_action
from app.services.portfolio_manager import portfolio_sync_status
from app.services.rules_approval import _entry_time_allowed


EXECUTABLE = {"ACTIVE", "PLANNED", "ARMED", "TRIGGERED", "ORDER_SUBMITTED"}
BLOCKED = {"NO_CHASE", "WAITLIST", "MISSED_BY_CAPITAL", "BLOCKED", "PAUSED", "INVALIDATED", "EXPIRED"}


def command_center_payload(session: Session, settings: Settings) -> dict:
    plans = list(session.scalars(select(TradePlan).order_by(TradePlan.updated_at.desc())))
    positions = list(session.scalars(select(Position).where(Position.status == "OPEN").order_by(Position.updated_at.desc())))
    executable = [_plan_view(session, plan, settings) for plan in plans if plan.priority_level in {"S", "A"} and plan.status in EXECUTABLE]
    executable.sort(key=lambda item: (_priority_rank(item["record"].priority_level), -item["record"].updated_at.timestamp()))
    blocked = [_plan_view(session, plan, settings) for plan in plans if plan.status in BLOCKED or plan.rules_approval_status.startswith("REJECTED")]
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
        "portfolio_sync": portfolio_sync_status(session),
    }


def _plan_view(session: Session, plan: TradePlan, settings: Settings) -> dict:
    status = status_for(plan.status)
    validation = _latest_validation(session, plan)
    current = float(plan.current_price or 0)
    entry = float(plan.breakout_entry_price or 0)
    no_chase = float(plan.no_chase_above or 0)
    entry_ok = bool(current and entry and current >= entry)
    chase_ok = bool(current and (not no_chase or current <= no_chase))
    has_position = bool(session.scalar(select(Position.id).where(Position.symbol == plan.symbol, Position.status == "OPEN")))
    has_order = bool(session.scalar(select(SimOrder.id).where(
        SimOrder.symbol == plan.symbol,
        SimOrder.status.in_({"SUBMITTED", "PARTIALLY_FILLED"}),
    )))
    sync = portfolio_sync_status(session)
    capital_ok = plan.capital_status == "CAPITAL_AVAILABLE" and sync.get("ok", False)
    checks = [
        ("当前价 >= 入场价", entry_ok),
        ("当前价 <= 禁止追价", chase_ok),
        ("计划状态 == TRIGGERED", plan.status == "TRIGGERED"),
        ("模拟交易开启", settings.enable_sim_trading),
        ("真实交易关闭", not settings.enable_real_trading),
        ("价差正常", validation.get("spread_pct") is not None and validation.get("spread_pct", 1) <= settings.max_spread_pct),
        ("成交量正常", validation.get("volume_ok") is True),
        ("短周期趋势未破坏", validation.get("short_trend_ok") is True),
        ("大盘不是 RISK_OFF", validation.get("market_state") not in {None, "RISK_OFF"}),
        ("当前时间允许开仓", _entry_time_allowed(settings)),
        ("资金可用", capital_ok),
        ("无同标的持仓", not has_position),
        ("无同标的未成交订单", not has_order),
    ]
    price_ready = entry_ok and chase_ok
    block_reason = (
        plan.rules_reject_reason
        or plan.capital_reason
        or (sync.get("error") or sync.get("reason") if not sync.get("ok") else "")
        or ("" if all(passed for _, passed in checks) else next(label for label, passed in checks if not passed))
    )
    return {
        "record": plan,
        "status": status,
        "next_action": describe_trade_plan_next_action(plan),
        "reason": plan.rules_reject_reason or plan.capital_reason or plan.reason,
        "price_gate_status": "价格条件已满足" if price_ready else "等待价格条件",
        "validation_status": "已推进为 TRIGGERED" if plan.status == "TRIGGERED" else ("价格已到，等待 sim loop 推进" if price_ready else "等待实时校验"),
        "rules_approval_status": status_for(plan.rules_approval_status).display_name if plan.rules_approval_status in {"ACTIVE"} else plan.rules_approval_status,
        "capital_status": plan.capital_status,
        "block_reason": block_reason,
        "checks": checks,
    }


def _priority_rank(priority_level: str) -> int:
    return {"S": 0, "A": 1, "B": 2, "C": 3}.get(priority_level, 4)


def _latest_validation(session: Session, plan: TradePlan) -> dict:
    log = session.scalar(
        select(AuditLog)
        .where(
            AuditLog.action == "TRADE_PLAN_VALIDATED",
            AuditLog.subject_type == "TradePlan",
            AuditLog.subject_id == plan.id,
        )
        .order_by(AuditLog.created_at.desc())
        .limit(1)
    )
    if not log:
        return {}
    try:
        return json.loads(log.payload_json or "{}")
    except json.JSONDecodeError:
        return {}
