import json
from datetime import UTC, datetime

from app.models import BattlePoolItem, CandidateStock, Position, SystemConfig
from app.services.freshness import freshness_context


def test_freshness_uses_real_database_update_times_and_next_schedule(session):
    candidate = CandidateStock(
        symbol="AAPL",
        name="Apple",
        pool_type="TREND_UP",
        selected_at=datetime(2026, 6, 11, 12, 0),
        updated_at=datetime(2026, 6, 11, 12, 30),
    )
    battle = BattlePoolItem(
        symbol="AAPL",
        priority_level="S",
        source_structure_id=1,
        structure_type="BOTTOM_STRUCTURE",
        reason="test",
        updated_at=datetime(2026, 6, 11, 14, 0),
    )
    session.add_all([candidate, battle])
    session.commit()

    result = freshness_context(session, datetime(2026, 6, 12, 13, 0, tzinfo=UTC))

    assert result["candidates"]["last_at"] == datetime(2026, 6, 11, 12, 30)
    assert result["battle"]["last_at"] == datetime(2026, 6, 11, 14, 0)
    assert result["candidates"]["next_at"] > datetime(2026, 6, 12, 13, 0)
    assert result["battle"]["schedule"] == "每根 60 分钟 K 线完成后重新评级"


def test_market_freshness_has_preopen_baseline_slot(session):
    result = freshness_context(session, datetime(2026, 6, 12, 12, 0, tzinfo=UTC), {"market"})

    assert result["market"]["next_at"] == datetime(2026, 6, 12, 13, 20)
    assert "开盘前 10 分钟" in result["market"]["schedule"]


def test_freshness_reports_missing_data_explicitly(session):
    result = freshness_context(session, datetime(2026, 6, 14, 12, 0, tzinfo=UTC))

    assert result["structures"]["status"] == "尚未产生数据"
    assert result["structures"]["last_at"] is None
    assert result["structures"]["next_at"] > datetime(2026, 6, 14, 12, 0)


def test_position_freshness_normalizes_database_and_portfolio_timezones(session):
    session.add(
        Position(
            symbol="US.EMR",
            entry_signal_id=0,
            entry_price=142,
            stop_price=139,
            shares=0,
            risk_amount=0,
            status="CLOSED",
            updated_at=datetime(2026, 6, 15, 15, 20),
        )
    )
    session.add(
        SystemConfig(
            key="portfolio_sync_status",
            value=json.dumps({"updated_at": "2026-06-15T15:20:30+00:00"}),
        )
    )
    session.commit()

    result = freshness_context(
        session,
        datetime(2026, 6, 15, 15, 21, tzinfo=UTC),
        {"positions"},
    )

    assert result["positions"]["last_at"] == datetime(2026, 6, 15, 15, 20, 30)
    assert result["positions"]["stale"] is False
