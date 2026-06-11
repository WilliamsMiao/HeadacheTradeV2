from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TradePlan


LIVE_PRICE_STATUSES = {
    "ACTIVE",
    "PLANNED",
    "ARMED",
    "WAIT_PULLBACK",
    "NO_CHASE",
    "TRIGGERED",
    "ORDER_SUBMITTED",
    "WAITLIST",
    "MISSED_BY_CAPITAL",
}


def refresh_trade_plan_prices(session: Session, quote_provider) -> dict[str, object]:
    plans = list(
        session.scalars(
            select(TradePlan).where(
                TradePlan.priority_level.in_({"S", "A"}),
                TradePlan.status.in_(LIVE_PRICE_STATUSES),
            )
        )
    )
    if not plans:
        return {"prices": {}, "updated_at": datetime.now(UTC).isoformat()}

    rows = quote_provider.get_market_snapshot(sorted({plan.symbol for plan in plans}))
    prices: dict[str, float] = {}
    changes: dict[str, float] = {}
    for row in rows:
        symbol = _symbol(row)
        price = _float(row, "last_price", "cur_price")
        if symbol and price > 0:
            prices[symbol] = price
            changes[symbol] = _float(row, "change_rate", "change_pct") / 100

    updated_at = datetime.now(UTC)
    for plan in plans:
        if plan.symbol not in prices:
            continue
        plan.current_price = prices[plan.symbol]
        plan.current_change_pct = changes.get(plan.symbol, 0)
        plan.last_validated_at = updated_at.replace(tzinfo=None)
    session.commit()
    return {
        "prices": prices,
        "changes": changes,
        "updated_at": updated_at.isoformat(),
    }


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
