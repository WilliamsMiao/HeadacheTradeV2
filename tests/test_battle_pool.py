import json
from datetime import datetime

from sqlalchemy import select

from app.models import BattlePoolItem, CandidateStock, DailyState, Indicator, KLine, StructureEvent
from app.services.battle_pool import rank_battle_pool, score_structure_event


def seed_structure(session, symbol="AAPL", rank_score=95, pivot_low=98):
    now = datetime.utcnow()
    candidate = CandidateStock(
        symbol=symbol,
        name=symbol,
        pool_type="TREND_UP",
        pool_types_json=json.dumps(["TREND_UP", "LOW_REBOUND"]),
        tags_json=json.dumps(["MA_ALIGNMENT_LONG", "MACD_LOW_IMPROVING", "KDJ_BOTTOM_DIVERGENCE"]),
        rank_score=rank_score,
        active=True,
    )
    event = StructureEvent(
        symbol=symbol,
        timeframe="60m",
        event_type="BOTTOM_STRUCTURE",
        event_ts=now,
        price=102,
        pivot_low=pivot_low,
        confirm_level=101,
        invalidation_level=pivot_low,
        reason="confirmed bottom",
    )
    session.add_all(
        [
            candidate,
            DailyState(symbol=symbol, as_of=now.date(), state="DAILY_STRONG_BULL", reason="strong"),
            event,
            KLine(
                symbol=symbol,
                timeframe="60m",
                ts=now,
                open=101,
                high=103,
                low=100,
                close=102,
                volume=2_000_000,
                turnover=204_000_000,
            ),
            Indicator(symbol=symbol, timeframe="60m", ts=now, atr=2),
        ]
    )
    session.commit()
    return event


def test_battle_score_uses_daily_state_tags_and_stop_distance(session):
    event = seed_structure(session)
    score = score_structure_event(session, event)
    assert score.priority == "S"
    assert score.direction == "LONG"
    assert "日线状态" in score.reason
    assert "结构止损距离可控" in score.reason


def test_battle_pool_enforces_s_and_a_capacity(session):
    for index in range(5):
        seed_structure(session, symbol=f"S{index}")
    counts = rank_battle_pool(session)
    items = list(session.scalars(select(BattlePoolItem).order_by(BattlePoolItem.score.desc())))
    assert counts["S"] == 3
    assert counts["A"] == 2
    assert [item.priority_level for item in items].count("S") == 3


def test_distant_stop_downgrades_structure(session):
    event = seed_structure(session, pivot_low=60)
    score = score_structure_event(session, event)
    assert score.score < 85
    assert "止损距离过远" in score.reason
