import json

from sqlalchemy import select

from app.models import CandidateSnapshot, CandidateStock
from app.services.screener import merge_candidates, screen_market


class ScreenerProvider:
    def __init__(self, rows):
        self.rows = rows

    def get_stock_filter_candidates(self):
        return self.rows


def row(symbol, pool, tag, turnover=80_000_000, volume_ratio=1.5):
    return {
        "symbol": symbol,
        "name": symbol,
        "market": "US",
        "pool_type": pool,
        "tag": tag,
        "cur_price": 50,
        "market_val": 10_000_000_000,
        "turnover_3d": turnover,
        "volume_ratio": volume_ratio,
    }


def test_candidate_merge_keeps_multiple_pools_and_tags():
    merged = merge_candidates(
        [
            row("AAPL", "LOW_REBOUND", "MACD_LOW_IMPROVING"),
            row("AAPL", "TREND_UP", "MA_ALIGNMENT_LONG"),
        ]
    )
    assert set(merged) == {"AAPL"}
    assert merged["AAPL"].pool_types == {"LOW_REBOUND", "TREND_UP"}
    assert merged["AAPL"].tags == {"MACD_LOW_IMPROVING", "MA_ALIGNMENT_LONG"}


def test_screen_market_is_deterministic_and_respects_capacity(session):
    rows = [
        row(f"S{i:03d}", "TREND_UP", "MA_ALIGNMENT_LONG", turnover=20_000_000 + i * 1_000_000)
        for i in range(320)
    ]
    rows.append(row("S319", "LOW_REBOUND", "KDJ_BOTTOM_DIVERGENCE", turnover=400_000_000))
    result = screen_market(session, ScreenerProvider(rows), max_candidates=300)

    candidates = list(
        session.scalars(
            select(CandidateStock)
            .where(CandidateStock.active.is_(True))
            .order_by(CandidateStock.rank_score.desc(), CandidateStock.symbol)
        )
    )
    assert result["unique_candidates"] == 320
    assert result["selected"] == 300
    assert len(candidates) == 300
    merged = session.scalar(select(CandidateStock).where(CandidateStock.symbol == "S319"))
    assert set(json.loads(merged.pool_types_json)) == {"LOW_REBOUND", "TREND_UP"}
    assert len(list(session.scalars(select(CandidateSnapshot)))) == 300
