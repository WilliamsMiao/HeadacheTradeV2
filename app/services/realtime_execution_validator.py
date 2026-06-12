from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Indicator, MarketState, TradePlan, TradingState
from app.services.audit import write_audit


VALIDATION_STATUSES = {"ACTIVE", "ARMED", "WAIT_PULLBACK", "PLANNED", "WAITLIST", "MISSED_BY_CAPITAL", "NO_CHASE"}
NEW_YORK = ZoneInfo("America/New_York")


def validate_active_trade_plans(session: Session, quote_provider, settings: Settings) -> dict[str, object]:
    plans = list(
        session.scalars(
            select(TradePlan)
            .where(
                TradePlan.priority_level.in_({"S", "A"}),
                TradePlan.direction == "LONG",
                TradePlan.status.in_(VALIDATION_STATUSES),
            )
            .order_by(TradePlan.created_at.asc(), TradePlan.id.asc())
        )
    )
    snapshots = quote_provider.get_market_snapshot([plan.symbol for plan in plans]) if plans else []
    by_symbol = {_symbol(row): row for row in snapshots}
    market = session.scalar(select(MarketState).order_by(MarketState.updated_at.desc()).limit(1))
    market_state_current = _market_state_is_current(market)
    contexts: dict[int, dict] = {}
    counts = {"validated": 0, "triggered": 0, "invalidated": 0, "no_chase": 0}

    for plan in plans:
        row = by_symbol.get(plan.symbol)
        if not row:
            plan.status = "PAUSED"
            plan.rules_reject_reason = "实时行情缺失"
            continue
        current = _float(row, "last_price", "cur_price")
        bid = _float(row, "bid_price", "bid_price_1")
        ask = _float(row, "ask_price", "ask_price_1")
        spread_available = bool(current and bid > 0 and ask >= bid)
        spread_pct = ((ask - bid) / current) if spread_available else None
        volume = _float(row, "volume", "turnover")
        volume_available = volume > 0
        short_trend_ok, short_trend_reason = _short_trend_status(session, plan.symbol, current)
        context = {
            "current_price": current,
            "bid_price": bid,
            "ask_price": ask,
            "spread_pct": spread_pct,
            "spread_available": spread_available,
            "volume": volume,
            "volume_ok": volume_available,
            "volume_available": volume_available,
            "short_trend_ok": short_trend_ok,
            "short_trend_reason": short_trend_reason,
            "market_state": market.state if market else "UNKNOWN",
            "market_state_available": market is not None and market_state_current,
            "market_state_updated_at": market.updated_at.isoformat() if market else None,
            "market_state_reason": (
                "市场风向标已按当前美股交易日刷新"
                if market_state_current
                else "市场风向标不是当前美股交易日数据，禁止沿用旧状态开仓"
            ),
            "validated_at": datetime.utcnow().isoformat(),
            "snapshot": row,
        }
        contexts[plan.id] = context
        plan.current_price = current
        plan.current_change_pct = _float(row, "change_rate", "change_pct") / 100
        plan.last_validated_at = datetime.utcnow()
        counts["validated"] += 1

        if current <= plan.stop_price:
            plan.status = "INVALIDATED"
            plan.rules_reject_reason = "当前价跌破止损价"
            counts["invalidated"] += 1
        elif plan.no_chase_above and current > plan.no_chase_above:
            plan.status = "NO_CHASE"
            plan.rules_reject_reason = "当前价超过禁止追价区"
            counts["no_chase"] += 1
        elif plan.breakout_entry_price and current >= plan.breakout_entry_price:
            plan.status = "TRIGGERED"
            plan.rules_reject_reason = ""
            counts["triggered"] += 1
        elif plan.breakout_entry_price and current >= plan.breakout_entry_price * 0.995:
            plan.status = "ARMED"
        else:
            plan.status = "ACTIVE"

        state = session.scalar(select(TradingState).where(TradingState.symbol == plan.symbol))
        if state and state.state == "COOLDOWN" and state.cooldown_until and state.cooldown_until >= datetime.utcnow().date():
            plan.status = "PAUSED"
            plan.rules_reject_reason = f"冷却期至 {state.cooldown_until}"
        write_audit(
            session,
            "TRADE_PLAN_VALIDATED",
            symbol=plan.symbol,
            subject_type="TradePlan",
            subject_id=plan.id,
            status=plan.status,
            reason=plan.rules_reject_reason,
            payload=context,
        )
    session.commit()
    return {**counts, "contexts": contexts}


def _market_state_is_current(market: MarketState | None, now: datetime | None = None) -> bool:
    if market is None or market.updated_at is None:
        return False
    now_utc = now or datetime.now(UTC)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=UTC)
    updated_utc = market.updated_at.replace(tzinfo=UTC) if market.updated_at.tzinfo is None else market.updated_at.astimezone(UTC)
    return updated_utc.astimezone(NEW_YORK).date() == now_utc.astimezone(NEW_YORK).date()


def _short_trend_status(session: Session, symbol: str, current: float) -> tuple[bool | None, str]:
    indicator = session.scalar(
        select(Indicator)
        .where(Indicator.symbol == symbol, Indicator.timeframe == "60m")
        .order_by(Indicator.ts.desc())
        .limit(1)
    )
    if not indicator or not indicator.ma20 or current <= 0:
        return None, "缺少最新 60 分钟 MA20"
    if current >= indicator.ma20:
        return True, f"当前价未跌破 60 分钟 MA20（{indicator.ma20:.2f}）"
    return False, f"当前价低于 60 分钟 MA20（{indicator.ma20:.2f}）"


def _symbol(row: dict) -> str:
    return str(row.get("code") or row.get("symbol") or "").upper().removeprefix("US.")


def _float(row: dict, *keys: str) -> float:
    for key in keys:
        try:
            value = float(row.get(key) or 0)
            if value:
                return value
        except (TypeError, ValueError):
            continue
    return 0.0
