from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import MarketState, TradePlan, TradingState
from app.services.audit import write_audit


VALIDATION_STATUSES = {"ACTIVE", "ARMED", "WAIT_PULLBACK", "PLANNED", "WAITLIST", "MISSED_BY_CAPITAL", "NO_CHASE"}


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
        spread_pct = ((ask - bid) / current) if current and bid > 0 and ask >= bid else 1.0
        volume = _float(row, "volume")
        context = {
            "current_price": current,
            "bid_price": bid,
            "ask_price": ask,
            "spread_pct": spread_pct,
            "volume_ok": volume > 0,
            "short_trend_ok": True,
            "market_state": market.state if market else "UNKNOWN",
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
