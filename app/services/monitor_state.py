from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    BattlePoolItem,
    CandidateStock,
    Position,
    StateTransitionLog,
    StructureEvent,
    TradePlan,
    TradingState,
)
from app.services.risk import get_or_create_risk_config


def refresh_monitor_state(session: Session, symbol: str) -> TradingState:
    record = session.scalar(select(TradingState).where(TradingState.symbol == symbol))
    if record is None:
        record = TradingState(symbol=symbol, state="IDLE")
        session.add(record)
        session.flush()

    position = session.scalar(select(Position).where(Position.symbol == symbol, Position.status == "OPEN"))
    latest_event = session.scalar(
        select(StructureEvent)
        .where(StructureEvent.symbol == symbol)
        .order_by(StructureEvent.event_ts.desc())
        .limit(1)
    )
    if position:
        if latest_event and latest_event.event_type == "TOP_STRUCTURE":
            _transition(session, record, "RISK_PROTECTION", latest_event.reason, "检查减仓或退出计划，不机械清仓")
        else:
            _transition(session, record, "SIM_POSITION", "模拟持仓持续跟踪", "等待止损、目标位或新的风险结构")
        session.commit()
        return record

    if latest_event and latest_event.event_type == "BOTTOM_FAILED":
        config = get_or_create_risk_config(session)
        record.cooldown_until = date.today() + timedelta(days=config.cooldown_days)
        _transition(session, record, "COOLDOWN", latest_event.reason, "冷却期结束后等待新的结构")
        session.commit()
        return record
    if record.cooldown_until and record.cooldown_until >= date.today():
        _transition(session, record, "COOLDOWN", f"冷却至 {record.cooldown_until}", "冷却期内只记录，不生成计划")
        session.commit()
        return record

    plan = session.scalar(
        select(TradePlan)
        .where(TradePlan.symbol == symbol, TradePlan.status == "ACTIVE")
        .order_by(TradePlan.updated_at.desc())
        .limit(1)
    )
    battle = session.scalar(
        select(BattlePoolItem).where(
            BattlePoolItem.symbol == symbol,
            BattlePoolItem.status == "ACTIVE",
        )
    )
    candidate = session.scalar(
        select(CandidateStock).where(
            CandidateStock.symbol == symbol,
            CandidateStock.active.is_(True),
        )
    )
    if plan:
        _transition(session, record, "PLAN_READY", plan.reason, "等待关键价位到达后人工复核")
    elif battle:
        _transition(session, record, "BATTLE_WATCH", battle.reason, battle.next_wait)
    elif latest_event:
        _transition(session, record, "STRUCTURE_DETECTED", latest_event.reason, "等待结构评分与重点作战池筛选")
    elif candidate:
        _transition(session, record, "CANDIDATE_POOL", candidate.selected_reason, "等待日线状态与 60 分钟结构")
    else:
        _transition(session, record, "IDLE", "未进入本轮候选池", "等待下一次全市场条件选股")
    session.commit()
    return record


def _transition(
    session: Session,
    record: TradingState,
    to_state: str,
    reason: str,
    next_wait: str,
) -> None:
    if record.state != to_state:
        session.add(
            StateTransitionLog(
                symbol=record.symbol,
                from_state=record.state,
                to_state=to_state,
                reason=reason,
            )
        )
    record.state = to_state
    record.last_reason = reason
    record.next_wait = next_wait
