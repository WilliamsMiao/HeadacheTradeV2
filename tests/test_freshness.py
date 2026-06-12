from datetime import UTC, datetime

from app.models import BattlePoolItem, CandidateStock
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


def test_freshness_reports_missing_data_explicitly(session):
    result = freshness_context(session, datetime(2026, 6, 14, 12, 0, tzinfo=UTC))

    assert result["structures"]["status"] == "尚未产生数据"
    assert result["structures"]["last_at"] is None
    assert result["structures"]["next_at"] > datetime(2026, 6, 14, 12, 0)
