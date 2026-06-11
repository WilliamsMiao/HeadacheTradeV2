from datetime import datetime

from sqlalchemy import select

from app.models import BattlePoolItem, CandidateStock, Indicator, StructureEvent, TradePlan
from app.services.trade_plan import generate_trade_plans


def seed_plan_source(session, *, with_atr=True):
    now = datetime.utcnow()
    event = StructureEvent(
        symbol="AAPL",
        timeframe="60m",
        event_type="BOTTOM_STRUCTURE",
        event_ts=now,
        price=102,
        pivot_low=95,
        confirm_level=101,
        invalidation_level=95,
        reason="confirmed",
    )
    session.add_all(
        [
            CandidateStock(
                symbol="AAPL",
                name="Apple",
                pool_type="TREND_UP",
                pool_types_json='["TREND_UP"]',
                tags_json='["MA_ALIGNMENT_LONG"]',
                rank_score=90,
                active=True,
            ),
            event,
        ]
    )
    session.flush()
    battle = BattlePoolItem(
        symbol="AAPL",
        direction="LONG",
        priority_level="S",
        source_structure_id=event.id,
        daily_state="DAILY_STRONG_BULL",
        structure_type="BOTTOM_STRUCTURE",
        score=92,
        reason="high quality",
        status="ACTIVE",
    )
    session.add(battle)
    if with_atr:
        session.add(Indicator(symbol="AAPL", timeframe="60m", ts=now, atr=2))
    session.commit()


def test_trade_plan_has_entry_stop_targets_and_risk_reward(session):
    seed_plan_source(session)
    result = generate_trade_plans(session)
    plan = session.scalar(select(TradePlan).where(TradePlan.symbol == "AAPL"))
    assert result["generated"] == 1
    assert plan.breakout_entry_price > 101
    assert plan.stop_price < 95
    assert plan.target_1 > plan.breakout_entry_price
    assert plan.target_2 > plan.target_1
    assert plan.risk_reward_1 == 1.5
    assert plan.risk_reward_2 == 2
    assert "失效" in plan.time_stop_rule


def test_trade_plan_is_not_generated_without_atr_stop_source(session):
    seed_plan_source(session, with_atr=False)
    result = generate_trade_plans(session)
    assert result["generated"] == 0
    assert result["skipped"] == 1
    assert session.scalar(select(TradePlan)) is None
