import json
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import STRUCTURE_TIMEFRAME
from app.models import BattlePoolItem, CandidateStock, DailyState, Indicator, KLine, StructureEvent


@dataclass(frozen=True)
class BattleScore:
    symbol: str
    structure_id: int
    direction: str
    priority: str
    score: float
    daily_state: str
    reason: str
    next_wait: str


def rank_battle_pool(session: Session) -> dict[str, int]:
    for item in session.scalars(select(BattlePoolItem).where(BattlePoolItem.status == "ACTIVE")):
        item.status = "ARCHIVED"

    latest_events = _latest_structure_events(session)
    scored = sorted(
        (score_structure_event(session, event) for event in latest_events),
        key=lambda item: (-item.score, item.symbol),
    )
    counts = {"S": 0, "A": 0, "B": 0, "C": 0}
    for score in scored:
        priority = score.priority
        if priority == "S" and counts["S"] >= 3:
            priority = "A"
        if priority == "A" and counts["A"] >= 10:
            priority = "B"
        counts[priority] += 1
        record = session.scalar(select(BattlePoolItem).where(BattlePoolItem.symbol == score.symbol))
        if record is None:
            record = BattlePoolItem(symbol=score.symbol)
            session.add(record)
        record.direction = score.direction
        record.priority_level = priority
        record.source_structure_id = score.structure_id
        record.daily_state = score.daily_state
        event = session.get(StructureEvent, score.structure_id)
        record.structure_type = event.event_type if event else ""
        record.score = score.score
        record.reason = score.reason
        record.next_wait = score.next_wait
        record.status = "ACTIVE"
        if event:
            event.quality_score = score.score
            event.battle_eligible = priority in {"S", "A"}
            event.direction = score.direction
            event.stage = _structure_stage(event.event_type)
            event.suggested_action = _suggested_action(event.event_type, score.daily_state)
    session.commit()
    return counts


def score_structure_event(session: Session, event: StructureEvent) -> BattleScore:
    daily = session.scalar(
        select(DailyState)
        .where(DailyState.symbol == event.symbol)
        .order_by(DailyState.as_of.desc())
        .limit(1)
    )
    candidate = session.scalar(
        select(CandidateStock).where(
            CandidateStock.symbol == event.symbol,
            CandidateStock.active.is_(True),
        )
    )
    latest = session.execute(
        select(KLine, Indicator)
        .join(
            Indicator,
            (Indicator.symbol == KLine.symbol)
            & (Indicator.timeframe == KLine.timeframe)
            & (Indicator.ts == KLine.ts),
        )
        .where(
            KLine.symbol == event.symbol,
            KLine.timeframe == STRUCTURE_TIMEFRAME,
            KLine.data_ok.is_(True),
        )
        .order_by(KLine.ts.desc())
        .limit(1)
    ).first()
    daily_state = daily.state if daily else "UNKNOWN"
    score = 0.0
    reasons: list[str] = []
    direction = _direction(event.event_type, daily_state)

    daily_points = _daily_support_points(event.event_type, daily_state)
    score += daily_points
    reasons.append(f"日线状态贡献 {daily_points:.0f} 分")

    structure_points = {
        "BOTTOM_STRUCTURE": 28,
        "TOP_STRUCTURE": 28,
        "TOP_INVALIDATED": 24,
        "BOTTOM_PASSIVATION": 12,
        "TOP_PASSIVATION": 12,
        "BOTTOM_FAILED": 0,
    }.get(event.event_type, 5)
    score += structure_points
    reasons.append(f"结构清晰度贡献 {structure_points} 分")

    age_hours = max(
        0.0,
        (datetime.now(timezone.utc).replace(tzinfo=None) - event.event_ts).total_seconds() / 3600,
    )
    freshness = 15 if age_hours <= 24 * 3 else 8 if age_hours <= 24 * 10 else 2
    score += freshness
    reasons.append(f"结构时效贡献 {freshness} 分")

    if candidate:
        candidate_points = min(18.0, candidate.rank_score * 0.12)
        tag_count = len(json.loads(candidate.tags_json or "[]"))
        tag_points = min(8.0, tag_count * 2.0)
        score += candidate_points + tag_points
        reasons.append(f"候选池排序与多标签贡献 {candidate_points + tag_points:.0f} 分")

    stop_penalty = 0.0
    if latest is not None:
        bar, indicator = latest
        stop_reference = event.pivot_low if direction == "LONG" else event.pivot_high
        if stop_reference and indicator.atr and bar.close:
            stop_distance = abs(bar.close - stop_reference) / bar.close
            if stop_distance <= 0.05:
                score += 12
                reasons.append("结构止损距离可控，贡献 12 分")
            elif stop_distance > 0.1:
                stop_penalty = 18
                score -= stop_penalty
                reasons.append("结构止损距离过远，扣 18 分")
        else:
            score -= 20
            reasons.append("缺少 ATR 或结构高低点，扣 20 分且不能生成计划")

    conflict = _has_structure_conflict(session, event)
    if conflict:
        score -= 12
        reasons.append("近期顶底结构冲突，扣 12 分")

    score = round(max(0.0, min(100.0, score)), 2)
    priority = "S" if score >= 85 else "A" if score >= 70 else "B" if score >= 50 else "C"
    next_wait = _next_wait(event.event_type, direction)
    return BattleScore(
        symbol=event.symbol,
        structure_id=event.id,
        direction=direction,
        priority=priority,
        score=score,
        daily_state=daily_state,
        reason="；".join(reasons),
        next_wait=next_wait,
    )


def _latest_structure_events(session: Session) -> list[StructureEvent]:
    candidates = list(
        session.scalars(
            select(StructureEvent)
            .join(
                CandidateStock,
                (CandidateStock.symbol == StructureEvent.symbol) & CandidateStock.active.is_(True),
            )
            .where(StructureEvent.timeframe == STRUCTURE_TIMEFRAME)
            .order_by(StructureEvent.symbol, StructureEvent.event_ts.desc())
        )
    )
    latest: dict[str, StructureEvent] = {}
    for event in candidates:
        latest.setdefault(event.symbol, event)
    return list(latest.values())


def _daily_support_points(event_type: str, daily_state: str) -> float:
    bullish = {
        "DAILY_STRONG_BULL": 30,
        "DAILY_WEAK_BULL": 22,
        "DAILY_RANGE": 12,
        "DAILY_WEAK_BEAR": 5,
        "DAILY_STRONG_BEAR": 0,
        "UNKNOWN": 0,
    }
    bearish = {
        "DAILY_STRONG_BEAR": 30,
        "DAILY_WEAK_BEAR": 22,
        "DAILY_RANGE": 12,
        "DAILY_WEAK_BULL": 5,
        "DAILY_STRONG_BULL": 0,
        "UNKNOWN": 0,
    }
    if event_type in {"BOTTOM_PASSIVATION", "BOTTOM_STRUCTURE", "TOP_INVALIDATED"}:
        return bullish.get(daily_state, 0)
    return bearish.get(daily_state, 0)


def _direction(event_type: str, daily_state: str) -> str:
    if event_type in {"BOTTOM_PASSIVATION", "BOTTOM_STRUCTURE", "TOP_INVALIDATED"}:
        return "LONG"
    if event_type == "TOP_STRUCTURE" and daily_state in {"DAILY_WEAK_BEAR", "DAILY_STRONG_BEAR"}:
        return "SHORT"
    return "RISK"


def _structure_stage(event_type: str) -> str:
    if event_type.endswith("PASSIVATION"):
        return "PASSIVATION"
    if event_type in {"BOTTOM_STRUCTURE", "TOP_STRUCTURE"}:
        return "CONFIRMED"
    if event_type.endswith("FAILED"):
        return "FAILED"
    if event_type.endswith("INVALIDATED"):
        return "INVALIDATED"
    return "UNKNOWN"


def _suggested_action(event_type: str, daily_state: str) -> str:
    if event_type == "BOTTOM_STRUCTURE":
        return "生成多头计划并等待关键价位"
    if event_type == "TOP_STRUCTURE":
        return "强多头中进入风险保护，弱空头中评估下行计划"
    if event_type == "TOP_INVALIDATED":
        return "评估强趋势恢复计划"
    return "继续观察，不能直接交易"


def _next_wait(event_type: str, direction: str) -> str:
    if event_type.endswith("PASSIVATION"):
        return "等待 60 分钟结构确认"
    if direction == "LONG":
        return "等待突破价、回踩区或低吸区到价后人工复核"
    if direction == "SHORT":
        return "等待跌破确认价后人工复核"
    return "观察风险是否扩散，不直接做空或清仓"


def _has_structure_conflict(session: Session, event: StructureEvent) -> bool:
    opposite = (
        {"TOP_PASSIVATION", "TOP_STRUCTURE"}
        if event.event_type.startswith("BOTTOM") or event.event_type == "TOP_INVALIDATED"
        else {"BOTTOM_PASSIVATION", "BOTTOM_STRUCTURE"}
    )
    recent = session.scalar(
        select(StructureEvent)
        .where(
            StructureEvent.symbol == event.symbol,
            StructureEvent.timeframe == event.timeframe,
            StructureEvent.event_type.in_(opposite),
            StructureEvent.event_ts <= event.event_ts,
        )
        .order_by(StructureEvent.event_ts.desc())
        .limit(1)
    )
    return bool(recent and (event.event_ts - recent.event_ts).days <= 5)
