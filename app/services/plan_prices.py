from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TradePlan
from app.services.position_sync import normalize_symbol


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

    symbols = sorted({_quote_symbol(plan.symbol) for plan in plans})
    rows = quote_provider.get_market_snapshot(symbols)
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
        symbol = normalize_symbol(plan.symbol)
        if symbol not in prices:
            continue
        plan.current_price = prices[symbol]
        plan.current_change_pct = changes.get(symbol, 0)
        plan.last_validated_at = updated_at.replace(tzinfo=None)
    session.commit()
    compatible_prices = _with_symbol_aliases(prices)
    compatible_changes = _with_symbol_aliases(changes)
    compatible_statuses = _with_symbol_aliases({normalize_symbol(plan.symbol): plan.status for plan in plans})
    return {
        "prices": compatible_prices,
        "changes": compatible_changes,
        "statuses": compatible_statuses,
        "updated_at": updated_at.isoformat(),
    }


def _symbol(row: dict) -> str:
    return normalize_symbol(row.get("code") or row.get("symbol"))


def _quote_symbol(symbol: str) -> str:
    return normalize_symbol(symbol).removeprefix("US.")


def _with_symbol_aliases(values: dict[str, object]) -> dict[str, object]:
    output: dict[str, object] = {}
    for symbol, value in values.items():
        normalized = normalize_symbol(symbol)
        if not normalized:
            continue
        output[normalized] = value
        output[normalized.removeprefix("US.")] = value
    return output


def _float(row: dict, *keys: str) -> float:
    for key in keys:
        try:
            value = float(row.get(key) or 0)
            if value:
                return value
        except (TypeError, ValueError):
            continue
    return 0.0
