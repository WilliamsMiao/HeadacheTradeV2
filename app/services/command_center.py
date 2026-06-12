import json
from datetime import UTC, datetime

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
    capital_ok = sync.get("ok", False) and sync.get("status") == "CAPITAL_AVAILABLE"
    checks = [
        ("当前价 >= 入场价", entry_ok, f"{current:.2f} / {entry:.2f}" if current and entry else "价格数据缺失"),
        ("当前价 <= 禁止追价", chase_ok, f"{current:.2f} / {no_chase:.2f}" if current and no_chase else "禁止追价线未设置"),
        ("计划状态 == TRIGGERED", plan.status == "TRIGGERED", f"当前状态：{plan.status}"),
        ("模拟交易开启", settings.enable_sim_trading, "系统配置"),
        ("真实交易关闭", not settings.enable_real_trading, "系统配置"),
        ("价差正常", _validation_check(validation, "spread_available", validation.get("spread_pct") is not None and validation.get("spread_pct", 1) <= settings.max_spread_pct), _spread_detail(validation, settings)),
        ("成交量正常", _validation_check(validation, "volume_available", validation.get("volume_ok") is True), _volume_detail(validation)),
        ("短周期趋势未破坏", _validation_value(validation, "short_trend_ok"), validation.get("short_trend_reason") or "等待 60 分钟指标"),
        ("大盘不是 RISK_OFF", _market_check(validation), f"最近校验：{validation.get('market_state') or '未知'}"),
        ("当前时间允许开仓", _entry_time_allowed(settings), "按美东交易时段"),
        ("资金可用", capital_ok, sync.get("reason") or sync.get("error") or "等待模拟账户同步"),
        ("无同标的持仓", not has_position, "本地模拟持仓"),
        ("无同标的未成交订单", not has_order, "本地模拟订单"),
    ]
    price_ready = entry_ok and chase_ok
    block_reason = (
        plan.rules_reject_reason
        or plan.capital_reason
        or (sync.get("error") or sync.get("reason") if not sync.get("ok") else "")
        or ("" if all(passed is True for _, passed, _ in checks) else next(
            f"{label}：{detail}" for label, passed, detail in checks if passed is not True
        ))
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
        payload = json.loads(log.payload_json or "{}")
        payload["_is_fresh"] = (datetime.now(UTC).replace(tzinfo=None) - log.created_at).total_seconds() <= 120
        return payload
    except json.JSONDecodeError:
        return {}


def _validation_check(validation: dict, availability_key: str, result: bool) -> bool | None:
    if not validation or not validation.get("_is_fresh"):
        return None
    if validation.get(availability_key) is not True:
        return None
    return result


def _validation_value(validation: dict, key: str) -> bool | None:
    if not validation or not validation.get("_is_fresh"):
        return None
    value = validation.get(key)
    return value if isinstance(value, bool) else None


def _market_check(validation: dict) -> bool | None:
    if not validation or not validation.get("_is_fresh") or validation.get("market_state_available") is not True:
        return None
    return validation.get("market_state") != "RISK_OFF"


def _spread_detail(validation: dict, settings: Settings) -> str:
    if not validation or not validation.get("_is_fresh"):
        return "最近 120 秒内没有实时校验"
    if validation.get("spread_available") is not True:
        return "OpenD 未返回有效买一/卖一"
    return f"{float(validation.get('spread_pct') or 0):.3%}，上限 {settings.max_spread_pct:.3%}"


def _volume_detail(validation: dict) -> str:
    if not validation or not validation.get("_is_fresh"):
        return "最近 120 秒内没有实时校验"
    if validation.get("volume_available") is not True:
        return "OpenD 未返回有效成交量"
    return f"实时快照成交量 {float(validation.get('volume') or 0):,.0f}"
