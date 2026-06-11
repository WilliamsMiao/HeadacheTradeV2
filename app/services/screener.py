import json
from dataclasses import dataclass, field
from datetime import datetime
from math import log10
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CandidateSnapshot, CandidateStock
from app.providers.base import MarketDataProvider


POOL_PRIORITY = {
    "LOW_REBOUND": 0,
    "TREND_UP": 1,
    "HIGH_RISK": 2,
    "WEAK_DOWN": 3,
}


@dataclass
class MergedCandidate:
    symbol: str
    name: str
    market: str
    pool_types: set[str] = field(default_factory=set)
    tags: set[str] = field(default_factory=set)
    metrics: dict[str, float | None] = field(default_factory=dict)


def screen_market(
    session: Session,
    provider: MarketDataProvider,
    *,
    max_candidates: int = 300,
    selected_at: datetime | None = None,
) -> dict[str, object]:
    raw_rows = provider.get_stock_filter_candidates()
    selected_at = selected_at or datetime.utcnow()
    merged = merge_candidates(raw_rows)
    ranked = sorted(
        (_score_candidate(candidate) for candidate in merged.values()),
        key=lambda item: (-item["rank_score"], item["symbol"]),
    )[:max_candidates]
    run_id = f"screen-{selected_at:%Y%m%d%H%M%S}-{uuid4().hex[:8]}"

    for record in session.scalars(select(CandidateStock).where(CandidateStock.active.is_(True))):
        record.active = False

    for item in ranked:
        record = session.scalar(select(CandidateStock).where(CandidateStock.symbol == item["symbol"]))
        if record is None:
            record = CandidateStock(symbol=item["symbol"])
            session.add(record)
        for field_name in (
            "name",
            "market",
            "pool_type",
            "pool_types_json",
            "tags_json",
            "selected_reason",
            "rank_score",
            "liquidity_score",
            "heat_score",
            "technical_score",
            "raw_metrics_json",
        ):
            setattr(record, field_name, item[field_name])
        record.active = True
        record.selected_at = selected_at
        session.add(
            CandidateSnapshot(
                run_id=run_id,
                symbol=item["symbol"],
                pool_type=item["pool_type"],
                pool_types_json=item["pool_types_json"],
                tags_json=item["tags_json"],
                rank_score=item["rank_score"],
                raw_metrics_json=item["raw_metrics_json"],
            )
        )
    session.commit()
    return {
        "run_id": run_id,
        "raw_matches": len(raw_rows),
        "unique_candidates": len(merged),
        "selected": len(ranked),
        "pool_counts": {
            pool: sum(pool in json.loads(item["pool_types_json"]) for item in ranked)
            for pool in POOL_PRIORITY
        },
    }


def merge_candidates(rows: list[dict[str, object]]) -> dict[str, MergedCandidate]:
    merged: dict[str, MergedCandidate] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "").upper()
        pool_type = str(row.get("pool_type") or "")
        tag = str(row.get("tag") or "")
        if not symbol or pool_type not in POOL_PRIORITY:
            continue
        candidate = merged.setdefault(
            symbol,
            MergedCandidate(
                symbol=symbol,
                name=str(row.get("name") or symbol),
                market=str(row.get("market") or "US"),
            ),
        )
        candidate.pool_types.add(pool_type)
        if tag:
            candidate.tags.add(tag)
        for key in ("cur_price", "market_val", "turnover_3d", "volume_ratio"):
            value = _number(row.get(key))
            if value is not None:
                previous = candidate.metrics.get(key)
                candidate.metrics[key] = value if previous is None else max(previous, value)
    return merged


def _score_candidate(candidate: MergedCandidate) -> dict[str, object]:
    turnover = candidate.metrics.get("turnover_3d") or 0
    volume_ratio = candidate.metrics.get("volume_ratio") or 1
    market_value = candidate.metrics.get("market_val") or 0
    liquidity_score = min(100.0, max(0.0, 24 * log10(max(turnover, 1) / 1_000_000 + 1)))
    heat_score = min(100.0, max(0.0, 42 * volume_ratio))
    technical_score = min(100.0, 25.0 * len(candidate.tags) + 8.0 * max(0, len(candidate.pool_types) - 1))
    size_bonus = min(10.0, max(0.0, log10(max(market_value, 1) / 2_000_000_000 + 1) * 8))
    rank_score = round(
        liquidity_score * 0.45 + heat_score * 0.2 + technical_score * 0.35 + size_bonus,
        2,
    )
    pool_types = sorted(candidate.pool_types, key=lambda item: POOL_PRIORITY[item])
    tags = sorted(candidate.tags)
    return {
        "symbol": candidate.symbol,
        "name": candidate.name,
        "market": candidate.market,
        "pool_type": pool_types[0],
        "pool_types_json": json.dumps(pool_types, ensure_ascii=False),
        "tags_json": json.dumps(tags, ensure_ascii=False),
        "selected_reason": f"命中 {len(tags)} 个技术标签，覆盖 {len(pool_types)} 类候选池；按流动性、活跃度与技术接近度排序。",
        "rank_score": rank_score,
        "liquidity_score": round(liquidity_score, 2),
        "heat_score": round(heat_score, 2),
        "technical_score": round(technical_score, 2),
        "raw_metrics_json": json.dumps(candidate.metrics, ensure_ascii=False),
    }


def _number(value) -> float | None:
    try:
        number = float(value)
        return number if number == number else None
    except (TypeError, ValueError):
        return None
