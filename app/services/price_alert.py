from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TradePlan
from app.providers.base import MarketDataProvider


def set_price_alerts(session: Session, provider: MarketDataProvider) -> dict[str, object]:
    plans = list(session.scalars(select(TradePlan).where(TradePlan.status == "ACTIVE")))
    armed = 0
    failed: dict[str, str] = {}
    for plan in plans:
        try:
            existing_notes = {
                str(item.get("note") or "")
                for item in provider.get_price_reminders(plan.symbol)
            }
            reminders = _plan_reminders(plan)
            for suffix, reminder_type, value in reminders:
                note = f"HT{plan.id}{suffix}"[:10]
                if note in existing_notes:
                    continue
                provider.set_price_reminder(plan.symbol, reminder_type, value, note)
            plan.alert_status = "ARMED"
            armed += 1
        except Exception as exc:
            plan.alert_status = "ERROR"
            failed[plan.symbol] = str(exc)
    session.commit()
    return {"armed": armed, "failed": len(failed), "failures": failed}


def _plan_reminders(plan: TradePlan) -> list[tuple[str, str, float]]:
    if plan.direction == "SHORT":
        return [
            ("E", "PRICE_DOWN", plan.breakout_entry_price),
            ("S", "PRICE_UP", plan.stop_price),
            ("1", "PRICE_DOWN", plan.target_1),
            ("2", "PRICE_DOWN", plan.target_2),
        ]
    return [
        ("E", "PRICE_UP", plan.breakout_entry_price),
        ("S", "PRICE_DOWN", plan.stop_price),
        ("1", "PRICE_UP", plan.target_1),
        ("2", "PRICE_UP", plan.target_2),
    ]
