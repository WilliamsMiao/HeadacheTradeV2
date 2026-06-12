from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AuditLog,
    BattlePoolItem,
    CandidateStock,
    MarketState,
    Position,
    SimOrder,
    StructureEvent,
    TradePlan,
)
from app.services.portfolio_manager import portfolio_sync_status

NEW_YORK = ZoneInfo("America/New_York")
HOURLY_REFRESH_TIMES = (time(10, 35), time(11, 35), time(12, 35), time(13, 35), time(14, 35), time(15, 35), time(16, 5))
MARKET_REFRESH_TIMES = (time(9, 20), *HOURLY_REFRESH_TIMES)


def freshness_context(
    session: Session,
    now: datetime | None = None,
    sections: set[str] | None = None,
) -> dict[str, dict]:
    now_utc = _as_utc(now or datetime.now(UTC))
    requested = sections or {
        "candidates", "structures", "battle", "plans", "orders",
        "positions", "market", "portfolio", "audit", "journal",
    }
    contexts = {}
    if "candidates" in requested:
        contexts["candidates"] = _freshness(_max_value(session, CandidateStock.updated_at), _next_weekday_time(now_utc, time(8, 45)), "美股开盘前每日完整扫描", now_utc, 26 * 60)
    if "structures" in requested:
        contexts["structures"] = _freshness(_max_value(session, StructureEvent.updated_at), _next_hourly_refresh(now_utc), "每根 60 分钟 K 线完成后刷新", now_utc, 20 * 60)
    if "battle" in requested:
        contexts["battle"] = _freshness(_max_value(session, BattlePoolItem.updated_at), _next_hourly_refresh(now_utc), "每根 60 分钟 K 线完成后重新评级", now_utc, 20 * 60)
    if "plans" in requested:
        contexts["plans"] = _freshness(_latest_plan_time(session), _next_sim_refresh(now_utc), "实时确认每 30 秒；结构每小时刷新", now_utc, 3)
    if "orders" in requested:
        contexts["orders"] = _freshness(_max_value(session, SimOrder.updated_at), _next_sim_refresh(now_utc), "模拟交易循环", now_utc, 3)
    if "positions" in requested:
        contexts["positions"] = _freshness(_max_value(session, Position.updated_at), _next_sim_refresh(now_utc), "模拟交易循环", now_utc, 3)
    if "market" in requested:
        contexts["market"] = _freshness(
            _max_value(session, MarketState.updated_at),
            _next_scheduled_refresh(now_utc, MARKET_REFRESH_TIMES),
            "开盘前 10 分钟生成当日基线；之后每根 60 分钟 K 线完成后刷新",
            now_utc,
            20 * 60,
        )
    if "portfolio" in requested:
        portfolio_at = _parse_datetime(portfolio_sync_status(session).get("updated_at"))
        contexts["portfolio"] = _freshness(portfolio_at, _next_sim_refresh(now_utc), "模拟账户同步", now_utc, 3)
    if "audit" in requested:
        contexts["audit"] = _freshness(_max_value(session, AuditLog.created_at), _next_sim_refresh(now_utc), "系统任务与模拟交易循环", now_utc, 3)
    if "journal" in requested:
        contexts["journal"] = _freshness(_latest_trade_activity(session), _next_sim_refresh(now_utc), "成交或持仓变化后更新", now_utc, 3)
    return contexts


def _freshness(last_at: datetime | None, next_at: datetime, schedule: str, now: datetime, stale_minutes: int) -> dict:
    last_utc = _as_utc(last_at) if last_at else None
    stale = last_utc is None or now - last_utc > timedelta(minutes=stale_minutes)
    return {
        "last_at": _naive_utc(last_utc) if last_utc else None,
        "next_at": _naive_utc(next_at),
        "schedule": schedule,
        "stale": stale,
        "status": "尚未产生数据" if last_utc is None else "数据可能已过期" if stale else "数据在有效期内",
    }


def _latest_plan_time(session: Session) -> datetime | None:
    updated = _max_value(session, TradePlan.updated_at)
    validated = _max_value(session, TradePlan.last_validated_at)
    return max((value for value in (updated, validated) if value), default=None)


def _latest_trade_activity(session: Session) -> datetime | None:
    position_at = _max_value(session, Position.updated_at)
    order_at = session.scalar(
        select(func.max(SimOrder.updated_at)).where(
            (SimOrder.dealt_qty > 0) | SimOrder.status.in_({"FILLED", "PARTIALLY_FILLED"})
        )
    )
    return max((value for value in (position_at, order_at) if value), default=None)


def _max_value(session: Session, column) -> datetime | None:
    return session.scalar(select(func.max(column)))


def _next_hourly_refresh(now_utc: datetime) -> datetime:
    return _next_scheduled_refresh(now_utc, HOURLY_REFRESH_TIMES)


def _next_scheduled_refresh(now_utc: datetime, slots: tuple[time, ...]) -> datetime:
    local = now_utc.astimezone(NEW_YORK)
    for day_offset in range(8):
        day = local.date() + timedelta(days=day_offset)
        if day.weekday() >= 5:
            continue
        for slot in slots:
            candidate = datetime.combine(day, slot, NEW_YORK)
            if candidate > local:
                return candidate.astimezone(UTC)
    return now_utc + timedelta(days=1)


def _next_weekday_time(now_utc: datetime, slot: time) -> datetime:
    local = now_utc.astimezone(NEW_YORK)
    for day_offset in range(8):
        day = local.date() + timedelta(days=day_offset)
        if day.weekday() >= 5:
            continue
        candidate = datetime.combine(day, slot, NEW_YORK)
        if candidate > local:
            return candidate.astimezone(UTC)
    return now_utc + timedelta(days=1)


def _next_sim_refresh(now_utc: datetime) -> datetime:
    return now_utc + timedelta(seconds=30)


def _parse_datetime(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _naive_utc(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)
