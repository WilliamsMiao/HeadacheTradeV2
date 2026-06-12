import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import AuditLog, Position, RiskConfig, SimOrder, SystemConfig
from app.services.portfolio_manager import portfolio_sync_status


RUNTIME_KEY = "risk_runtime_overrides"
FIELDS = (
    "risk_per_trade_pct",
    "max_positions",
    "max_symbol_position_pct",
    "max_daily_new_trades",
    "max_daily_loss_pct",
    "max_consecutive_losses",
    "force_intraday_exit",
    "enable_overnight_hold",
    "no_new_entry_before_minutes_after_open",
    "no_new_entry_before_close_minutes",
)


def effective_risk_settings(session: Session, settings: Settings) -> Settings:
    overrides = _runtime_overrides(session)
    valid = {key: overrides[key] for key in FIELDS if key in overrides}
    return settings.model_copy(update=valid)


def risk_page_context(session: Session, settings: Settings, config: RiskConfig) -> dict:
    effective = effective_risk_settings(session, settings)
    sync = portfolio_sync_status(session)
    equity = float(sync.get("account_equity") or 0)
    sync_at = _parse_dt(sync.get("updated_at"))
    sync_stale = not sync_at or datetime.now(UTC) - sync_at > timedelta(minutes=3)
    equity_ok = (
        bool(sync.get("ok"))
        and sync.get("account_equity_source") == "FUTU_SIM_ACCOUNT"
        and sync.get("account_equity_sync_status") == "OK"
        and equity > 0
        and not sync_stale
    )
    open_positions = session.scalar(select(func.count(Position.id)).where(Position.status == "OPEN")) or 0
    today_orders = session.scalar(
        select(func.count(SimOrder.id)).where(
            SimOrder.side == "BUY",
            func.date(SimOrder.submitted_at) == datetime.now(UTC).date().isoformat(),
        )
    ) or 0
    blockers = []
    if not equity_ok:
        blockers.append("无法读取新鲜的 Futu 模拟账户权益")
    if not effective.enable_sim_trading:
        blockers.append("模拟交易总开关关闭")
    if open_positions >= effective.max_positions:
        blockers.append("已达到最大持仓数")
    if today_orders >= effective.max_daily_new_trades:
        blockers.append("已达到今日最大新开仓次数")
    values = {field: getattr(effective, field) for field in FIELDS}
    stored = _runtime_overrides(session)
    sources = {field: "页面运行时配置" if field in stored else "服务器环境配置" for field in FIELDS}
    audits = list(
        session.scalars(
            select(AuditLog)
            .where(AuditLog.action == "RISK_CONFIG_UPDATED")
            .order_by(AuditLog.created_at.desc())
            .limit(10)
        )
    )
    return {
        "portfolio": sync,
        "equity": equity,
        "equity_ok": equity_ok,
        "equity_stale": sync_stale,
        "allows_entry": not blockers,
        "blockers": blockers,
        "open_positions": open_positions,
        "today_orders": today_orders,
        "effective": values,
        "sources": sources,
        "risk_level": risk_level(values),
        "max_loss_amount": equity * effective.risk_per_trade_pct,
        "max_symbol_amount": equity * effective.max_symbol_position_pct,
        "audits": audits,
        "legacy_config": config,
    }


def update_risk_settings(session: Session, settings: Settings, values: dict, reason: str) -> dict:
    old_effective = {field: getattr(effective_risk_settings(session, settings), field) for field in FIELDS}
    normalized = {field: values[field] for field in FIELDS}
    _validate(normalized)
    record = session.scalar(select(SystemConfig).where(SystemConfig.key == RUNTIME_KEY))
    if record is None:
        record = SystemConfig(key=RUNTIME_KEY)
        session.add(record)
    record.value = json.dumps(normalized, ensure_ascii=False)
    audit = AuditLog(
        action="RISK_CONFIG_UPDATED",
        subject_type="RiskConfig",
        status="SUCCESS",
        reason=reason or "用户手动修改风控配置",
        payload_json=json.dumps(
            {
                "old_values": old_effective,
                "new_values": normalized,
                "effective_values": normalized,
                "override_sources": {field: "页面运行时配置" for field in FIELDS},
            },
            ensure_ascii=False,
        ),
    )
    session.add(audit)
    session.commit()
    return normalized


def risk_level(values: dict) -> str:
    if values["risk_per_trade_pct"] > 0.02 or values["max_positions"] > 5 or values["max_daily_loss_pct"] > 0.05:
        return "危险"
    if values["risk_per_trade_pct"] > 0.01 or values["max_symbol_position_pct"] > 0.5 or values["enable_overnight_hold"]:
        return "激进"
    if values["risk_per_trade_pct"] <= 0.0025 and values["max_positions"] <= 1:
        return "保守"
    return "标准"


def _validate(values: dict) -> None:
    if not 0 < values["risk_per_trade_pct"] <= 0.05:
        raise ValueError("单笔风险必须大于 0 且不得超过 5%")
    if not 1 <= values["max_positions"] <= 10:
        raise ValueError("最大持仓数必须在 1–10 之间")
    if not 0 < values["max_symbol_position_pct"] <= 1:
        raise ValueError("单股最大仓位必须在 0–100% 之间")
    if not 1 <= values["max_daily_new_trades"] <= 20:
        raise ValueError("每日最大新开仓数必须在 1–20 之间")
    if not 0 < values["max_daily_loss_pct"] <= 0.1:
        raise ValueError("每日亏损停止线必须在 0–10% 之间")


def _runtime_overrides(session: Session) -> dict:
    record = session.scalar(select(SystemConfig).where(SystemConfig.key == RUNTIME_KEY))
    if not record:
        return {}
    try:
        return json.loads(record.value)
    except json.JSONDecodeError:
        return {}


def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except ValueError:
        return None
