from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import AuditLog, Position, SimOrder, TradePlan, TradingState
from app.services.audit import write_audit
from app.services.portfolio_manager import PortfolioState, capital_allows_new_order


@dataclass(frozen=True)
class ApprovalDecision:
    decision: str
    reason: str

    @property
    def approved(self) -> bool:
        return self.decision == "APPROVED_FOR_SIM_TRADE"


def rules_approve_trade_plan(
    session: Session,
    plan: TradePlan,
    realtime_context: dict,
    portfolio_state: PortfolioState,
    settings: Settings,
) -> ApprovalDecision:
    risk_block = _daily_risk_block(session, settings)
    if risk_block:
        return _reject(session, plan, "REJECTED_BY_RISK", risk_block, realtime_context)
    spread_available = realtime_context.get("spread_available", "spread_pct" in realtime_context)
    volume_available = realtime_context.get("volume_available", "volume_ok" in realtime_context)
    market_state_available = realtime_context.get("market_state_available", "market_state" in realtime_context)
    checks = [
        (settings.enable_sim_trading, "REJECTED_BY_RISK", "模拟交易总开关未开启"),
        (not settings.enable_real_trading, "REJECTED_BY_RISK", "真实交易配置必须关闭"),
        (plan.priority_level in {"S", "A"}, "REJECTED_BY_RISK", "仅 S/A 级允许自动模拟交易"),
        (plan.direction == "LONG", "REJECTED_BY_RISK", "第一版只允许多头"),
        (plan.status == "TRIGGERED", "REJECTED_BY_PRICE", "计划尚未完整触发"),
        (float(realtime_context.get("current_price") or 0) >= float(plan.breakout_entry_price or 0), "REJECTED_BY_PRICE", "尚未达到突破价"),
        (float(realtime_context.get("current_price") or 0) <= float(plan.no_chase_above or 0), "REJECTED_BY_PRICE", "超过禁止追价线"),
        (spread_available is True, "REJECTED_BY_DATA", "实时买卖价不可用"),
        (float(realtime_context.get("spread_pct") or 0) <= settings.max_spread_pct, "REJECTED_BY_DATA", "买卖价差过大"),
        (volume_available is True, "REJECTED_BY_DATA", "实时成交量不可用"),
        (realtime_context.get("volume_ok") is True, "REJECTED_BY_DATA", "实时成交量异常"),
        (realtime_context.get("short_trend_ok") is not None, "REJECTED_BY_DATA", "短周期趋势尚未完成校验"),
        (realtime_context.get("short_trend_ok") is True, "REJECTED_BY_PRICE", "短周期趋势已破坏"),
        (market_state_available is True, "REJECTED_BY_DATA", "市场状态尚未完成校验"),
        (realtime_context.get("market_state") != "RISK_OFF", "REJECTED_BY_MARKET", "市场处于风险关闭状态"),
        (_entry_time_allowed(settings), "REJECTED_BY_RISK", "当前处于禁止新开仓时间"),
    ]
    for passed, decision, reason in checks:
        if not passed:
            return _reject(session, plan, decision, reason, realtime_context)

    allowed, capital_reason = capital_allows_new_order(session, plan, portfolio_state, settings)
    if not allowed:
        plan.status = "MISSED_BY_CAPITAL" if plan.status == "TRIGGERED" else "WAITLIST"
        plan.capital_status = portfolio_state.status
        plan.capital_reason = capital_reason
        plan.missed_by_capital_at = datetime.utcnow()
        plan.missed_by_capital_price = realtime_context.get("current_price")
        write_audit(
            session,
            "MISSED_BY_CAPITAL",
            symbol=plan.symbol,
            subject_type="TradePlan",
            subject_id=plan.id,
            status="BLOCKED",
            reason=capital_reason,
            payload=realtime_context,
        )
        session.commit()
        return ApprovalDecision("REJECTED_BY_CAPITAL", capital_reason)

    plan.rules_approval_status = "APPROVED_FOR_SIM_TRADE"
    plan.rules_reject_reason = ""
    write_audit(
        session,
        "RULES_APPROVED",
        symbol=plan.symbol,
        subject_type="TradePlan",
        subject_id=plan.id,
        status="APPROVED",
        reason="全部自动审批规则通过",
        payload=realtime_context,
    )
    session.commit()
    return ApprovalDecision("APPROVED_FOR_SIM_TRADE", "全部自动审批规则通过")


def _daily_risk_block(session: Session, settings: Settings) -> str:
    today = datetime.utcnow().date()
    submitted = session.scalar(
        select(func.count(AuditLog.id)).where(
            AuditLog.action == "SIM_ORDER_SUBMITTED",
            func.date(AuditLog.created_at) == today.isoformat(),
        )
    ) or 0
    if submitted >= settings.max_daily_new_trades:
        return "已达到当日最大新开仓次数"
    closed = list(
        session.scalars(
            select(Position)
            .where(Position.status == "CLOSED", func.date(Position.updated_at) == today.isoformat())
            .order_by(Position.updated_at.desc())
        )
    )
    losses = [position.current_r for position in closed if position.current_r < 0]
    if sum(losses) <= -(settings.max_daily_loss_pct / max(settings.risk_per_trade_pct, 0.0001)):
        return "已触发当日亏损停止线"
    consecutive = 0
    for position in closed:
        if position.current_r < 0:
            consecutive += 1
        else:
            break
    if consecutive >= settings.max_consecutive_losses:
        return "已达到最大连续亏损次数"
    return ""


def _reject(session, plan, decision, reason, context):
    plan.rules_approval_status = decision
    plan.rules_reject_reason = reason
    write_audit(
        session,
        "RULES_REJECTED",
        symbol=plan.symbol,
        subject_type="TradePlan",
        subject_id=plan.id,
        status="REJECTED",
        reason=reason,
        payload=context,
    )
    session.commit()
    return ApprovalDecision(decision, reason)


def _entry_time_allowed(settings: Settings, now: datetime | None = None) -> bool:
    now = now or datetime.now(ZoneInfo("America/New_York"))
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    market_open = 9 * 60 + 30
    market_close = 16 * 60
    return (
        minutes >= market_open + settings.no_new_entry_before_minutes_after_open
        and minutes < market_close - settings.no_new_entry_before_close_minutes
    )
