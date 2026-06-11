import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import STRUCTURE_TIMEFRAME
from app.models import BattlePoolItem, CandidateStock, Indicator, StructureEvent, TradePlan


PLAN_EVENT_TYPES = {"BOTTOM_STRUCTURE", "TOP_STRUCTURE", "TOP_INVALIDATED"}


def generate_trade_plans(session: Session) -> dict[str, int]:
    active_items = list(
        session.scalars(
            select(BattlePoolItem).where(
                BattlePoolItem.status == "ACTIVE",
                BattlePoolItem.priority_level.in_({"S", "A"}),
            )
        )
    )
    active_keys: set[tuple[str, int]] = set()
    generated = 0
    skipped = 0
    for item in active_items:
        event = session.get(StructureEvent, item.source_structure_id)
        if event is None or event.event_type not in PLAN_EVENT_TYPES or item.direction == "RISK":
            skipped += 1
            continue
        plan_values = build_trade_plan_values(session, item, event)
        if plan_values is None:
            skipped += 1
            continue
        active_keys.add((item.symbol, event.id))
        plan = session.scalar(
            select(TradePlan).where(
                TradePlan.symbol == item.symbol,
                TradePlan.source_structure_id == event.id,
            )
        )
        if plan is None:
            plan = TradePlan(
                symbol=item.symbol,
                source_structure_id=event.id,
                battle_pool_id=item.id,
                stop_price=plan_values["stop_price"],
                target_1=plan_values["target_1"],
                target_2=plan_values["target_2"],
                risk_reward_1=plan_values["risk_reward_1"],
                risk_reward_2=plan_values["risk_reward_2"],
                trailing_rule=plan_values["trailing_rule"],
                time_stop_rule=plan_values["time_stop_rule"],
                invalid_condition=plan_values["invalid_condition"],
                reason=plan_values["reason"],
            )
            session.add(plan)
        for key, value in plan_values.items():
            setattr(plan, key, value)
        plan.battle_pool_id = item.id
        plan.status = "ACTIVE"
        generated += 1

    for plan in session.scalars(
        select(TradePlan).where(
            TradePlan.status.in_(
                {
                    "PLANNED",
                    "ACTIVE",
                    "ARMED",
                    "WAIT_PULLBACK",
                    "NO_CHASE",
                    "TRIGGERED",
                    "WAITLIST",
                    "MISSED_BY_CAPITAL",
                    "PAUSED",
                }
            )
        )
    ):
        if (plan.symbol, plan.source_structure_id) not in active_keys:
            plan.status = "INVALIDATED"
            plan.invalid_condition = f"{plan.invalid_condition}；对应结构已不在 S/A 级重点作战池"
    session.commit()
    return {"generated": generated, "skipped": skipped}


def build_trade_plan_values(
    session: Session,
    item: BattlePoolItem,
    event: StructureEvent,
) -> dict[str, object] | None:
    indicator = session.scalar(
        select(Indicator).where(
            Indicator.symbol == event.symbol,
            Indicator.timeframe == STRUCTURE_TIMEFRAME,
            Indicator.ts == event.event_ts,
        )
    )
    if indicator is None or indicator.atr is None or indicator.atr <= 0:
        return None
    atr = indicator.atr
    candidate = session.scalar(select(CandidateStock).where(CandidateStock.symbol == event.symbol))
    name = candidate.name if candidate else event.symbol
    tags = json.loads(candidate.tags_json or "[]") if candidate else []

    if item.direction == "LONG":
        reference = event.confirm_level or event.trigger_level or event.price
        stop_reference = event.pivot_low if event.event_type == "BOTTOM_STRUCTURE" else event.invalidation_level
        if reference is None or stop_reference is None:
            return None
        entry = reference + 0.1 * atr
        stop = stop_reference - 0.5 * atr
        if stop <= 0 or stop >= entry:
            return None
        risk = entry - stop
        target_1 = entry + 1.5 * risk
        target_2 = entry + 2.0 * risk
        entry_mode = "BREAKOUT" if event.event_type == "TOP_INVALIDATED" else "BREAKOUT_OR_PULLBACK"
        invalid_condition = f"60 分钟收盘跌破 {stop_reference:.2f} 或结构被标记为失败"
        low_absorb_low = max(stop + 0.25 * atr, stop_reference)
        low_absorb_high = stop_reference + 0.6 * atr
    else:
        reference = event.confirm_level or event.trigger_level or event.price
        stop_reference = event.pivot_high or event.invalidation_level
        if reference is None or stop_reference is None:
            return None
        entry = reference - 0.1 * atr
        stop = stop_reference + 0.5 * atr
        if entry <= 0 or stop <= entry:
            return None
        risk = stop - entry
        target_1 = max(0.01, entry - 1.5 * risk)
        target_2 = max(0.01, entry - 2.0 * risk)
        entry_mode = "BREAKDOWN_REVIEW"
        invalid_condition = f"60 分钟收盘重新站上 {stop_reference:.2f}，下行计划失效"
        low_absorb_low = None
        low_absorb_high = None

    buffer = max(0.05 * atr, reference * 0.002)
    return {
        "name": name,
        "direction": item.direction,
        "daily_state": item.daily_state,
        "structure_type": event.event_type,
        "priority_level": item.priority_level,
        "entry_mode": entry_mode,
        "breakout_entry_price": round(entry, 4),
        "pullback_entry_low": round(reference - buffer, 4),
        "pullback_entry_high": round(reference + buffer, 4),
        "low_absorb_entry_low": round(low_absorb_low, 4) if low_absorb_low is not None else None,
        "low_absorb_entry_high": round(low_absorb_high, 4) if low_absorb_high is not None else None,
        "stop_price": round(stop, 4),
        "target_1": round(target_1, 4),
        "target_2": round(target_2, 4),
        "trailing_rule": "达到 1R 后止损抬至成本附近；达到 1.5R 后锁定 0.5R；达到 2R 后按 60 分钟前低/前高、MA20 与 ATR 收紧。",
        "time_stop_rule": (
            "突破后 2 至 3 根 60 分钟 K 未继续走强则计划失效"
            if item.direction == "LONG"
            else "跌破后 2 至 3 根 60 分钟 K 未继续走弱则计划失效"
        ),
        "invalid_condition": invalid_condition,
        "risk_reward_1": 1.5,
        "risk_reward_2": 2.0,
        "no_chase_above": round(entry + 0.5 * atr, 4) if item.direction == "LONG" else None,
        "no_chase_below": round(entry - 0.5 * atr, 4) if item.direction != "LONG" else None,
        "activation_status": "PLANNED",
        "manual_checklist_json": json.dumps(
            [
                "结构仍然有效",
                "实时价格未超过禁止追价线",
                "盘口价差符合限制",
                "市场与资金闸门允许",
                "无同标的持仓或未完成订单",
            ],
            ensure_ascii=False,
        ),
        "reason": (
            f"{item.priority_level} 级重点作战；{item.reason}；"
            f"候选标签：{', '.join(tags) if tags else '无'}。计划只提供关键价位，必须人工复核。"
        ),
    }
