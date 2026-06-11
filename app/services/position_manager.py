from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Position, SimOrder
from app.services.audit import write_audit


def manage_positions(session: Session, quote_provider, trade_provider, settings: Settings) -> dict[str, int]:
    positions = list(session.scalars(select(Position).where(Position.status == "OPEN")))
    snapshots = quote_provider.get_market_snapshot([position.symbol for position in positions]) if positions else []
    by_symbol = {
        str(row.get("code") or row.get("symbol") or "").upper().removeprefix("US."): row
        for row in snapshots
    }
    submitted = 0
    for position in positions:
        row = by_symbol.get(position.symbol)
        if not row:
            continue
        current = float(row.get("last_price") or row.get("cur_price") or 0)
        risk = max(position.entry_price - position.stop_price, 0.0001)
        position.current_r = (current - position.entry_price) / risk
        position.max_r = max(position.max_r, position.current_r)
        position.min_r = min(position.min_r, position.current_r)

        qty = 0
        reason = ""
        if current <= max(position.stop_price, position.trailing_stop_price or 0):
            qty, reason = position.shares, "HARD_STOP"
        elif position.target_2 and current >= position.target_2:
            qty, reason = position.shares, "TARGET_2_OR_TRAILING"
        elif position.target_1 and current >= position.target_1 and not position.partial_exit_done:
            qty, reason = max(1, position.shares // 2), "TARGET_1_PARTIAL"
            position.partial_exit_done = True
            position.stop_price = max(position.stop_price, position.entry_price)
        elif position.current_r >= 1.5:
            position.trailing_stop_price = max(
                position.trailing_stop_price or position.stop_price,
                position.entry_price + 0.5 * risk,
            )
            write_audit(
                session,
                "TRAILING_STOP_UPDATED",
                symbol=position.symbol,
                subject_type="Position",
                subject_id=position.id,
                payload={"trailing_stop": position.trailing_stop_price, "current_r": position.current_r},
            )
        if settings.force_intraday_exit and _near_close():
            qty, reason = position.shares, "FORCED_INTRADAY_EXIT"

        if qty and not session.scalar(
            select(SimOrder).where(
                SimOrder.symbol == position.symbol,
                SimOrder.side == "SELL",
                SimOrder.status.in_({"SUBMITTED", "PARTIALLY_FILLED"}),
            )
        ):
            response = trade_provider.place_simulated_order(position.symbol, "SELL", qty, current)
            order = SimOrder(
                symbol=position.symbol,
                side="SELL",
                qty=qty,
                limit_price=current,
                submitted_price=current,
                futu_order_id=str(response.get("order_id") or ""),
                status="SUBMITTED",
                reason=reason,
            )
            session.add(order)
            position.exit_reason = reason
            write_audit(
                session,
                "STOP_LOSS_TRIGGERED" if reason == "HARD_STOP" else "TAKE_PROFIT_TRIGGERED",
                symbol=position.symbol,
                subject_type="Position",
                subject_id=position.id,
                reason=reason,
                payload={"price": current, "qty": qty},
            )
            submitted += 1
    session.commit()
    return {"managed": len(positions), "exit_orders_submitted": submitted}


def _near_close(now: datetime | None = None) -> bool:
    now = now or datetime.now(ZoneInfo("America/New_York"))
    return now.weekday() < 5 and (now.hour, now.minute) >= (15, 45)
