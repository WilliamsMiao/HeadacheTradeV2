from datetime import datetime

from app.models import TradePlan
from app.services.price_alert import set_price_alerts


class AlertProvider:
    def __init__(self):
        self.created = []

    def get_price_reminders(self, symbol):
        return []

    def set_price_reminder(self, symbol, reminder_type, value, note):
        self.created.append((symbol, reminder_type, value, note))
        return len(self.created)


def test_trade_plan_arms_four_futu_price_reminders(session):
    session.add(
        TradePlan(
            symbol="AAPL",
            name="Apple",
            direction="LONG",
            source_structure_id=1,
            battle_pool_id=1,
            daily_state="DAILY_STRONG_BULL",
            structure_type="BOTTOM_STRUCTURE",
            priority_level="S",
            entry_mode="BREAKOUT",
            breakout_entry_price=102,
            stop_price=95,
            target_1=112.5,
            target_2=116,
            trailing_rule="trail",
            time_stop_rule="time",
            invalid_condition="invalid",
            risk_reward_1=1.5,
            risk_reward_2=2,
            status="ACTIVE",
            reason="test",
            created_at=datetime.utcnow(),
        )
    )
    session.commit()
    provider = AlertProvider()
    result = set_price_alerts(session, provider)
    assert result == {"armed": 1, "failed": 0, "failures": {}}
    assert [item[1] for item in provider.created] == ["PRICE_UP", "PRICE_DOWN", "PRICE_UP", "PRICE_UP"]
