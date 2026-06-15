from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import (
    AuditLog,
    BattlePoolItem,
    CandidateStock,
    KLine,
    Position,
    SimOrder,
    StructureEvent,
    TradePlan,
)
from app.presentation import label_for
from app.presentation_status import StatusPresentation, status_for
from app.services.command_center import plan_view_model
from app.services.next_action import describe_position_next_action
from app.services.portfolio_manager import portfolio_sync_status
from app.services.risk_control import effective_risk_settings


ACTIVE_PLAN_STATUSES = {
    "PLANNED",
    "ACTIVE",
    "ARMED",
    "TRIGGERED",
    "ORDER_SUBMITTED",
    "IN_POSITION",
    "WAIT_PULLBACK",
    "WAITLIST",
    "MISSED_BY_CAPITAL",
    "NO_CHASE",
    "BLOCKED",
    "PAUSED",
}
TERMINAL_KLINE_TIMEFRAMES = {"1m", "5m", "15m", "60m", "1d"}


def terminal_summary(session: Session, settings: Settings) -> dict:
    effective = effective_risk_settings(session, settings)
    portfolio = portfolio_sync_status(session)
    positions = list(session.scalars(select(Position).where(Position.status == "OPEN")))
    today = datetime.now(UTC).date().isoformat()
    today_orders = session.scalar(
        select(func.count(SimOrder.id)).where(
            SimOrder.side == "BUY",
            func.date(SimOrder.submitted_at) == today,
        )
    ) or 0
    realized_r = session.scalar(
        select(func.coalesce(func.sum(Position.current_r), 0)).where(
            Position.status != "OPEN",
            func.date(Position.updated_at) == today,
        )
    ) or 0
    equity_ok = (
        portfolio.get("ok") is True
        and portfolio.get("account_equity_source") == "FUTU_SIM_ACCOUNT"
        and portfolio.get("account_equity_sync_status") == "OK"
        and float(portfolio.get("account_equity") or 0) > 0
    )
    can_open = (
        effective.enable_sim_trading
        and not effective.enable_real_trading
        and equity_ok
        and len(positions) < effective.max_positions
        and today_orders < effective.max_daily_new_trades
    )
    stop_reason = ""
    if not effective.enable_sim_trading:
        stop_reason = "模拟交易循环已关闭。"
    elif effective.enable_real_trading:
        stop_reason = "安全配置异常：真实交易必须保持关闭。"
    elif not equity_ok:
        stop_reason = portfolio.get("error") or portfolio.get("reason") or "模拟账户权益尚未完成同步。"
    elif len(positions) >= effective.max_positions:
        stop_reason = "当前持仓数量已达到风控上限。"
    elif today_orders >= effective.max_daily_new_trades:
        stop_reason = "今日新开仓数量已达到风控上限。"

    return {
        "mode": "SIM_TRADING" if effective.enable_sim_trading else "SIM_DISABLED",
        "real_trading": "DISABLED",
        "sim_loop_status": "OK" if effective.enable_sim_trading else "STOPPED",
        "futu_quote_status": "OK" if portfolio.get("ok") else "UNKNOWN",
        "futu_trade_status": "OK" if portfolio.get("ok") else "UNKNOWN",
        "account_equity": float(portfolio.get("account_equity") or 0),
        "account_equity_source": portfolio.get("account_equity_source", "UNKNOWN"),
        "account_equity_sync_status": portfolio.get("account_equity_sync_status", "FAILED"),
        "account_equity_synced_at": portfolio.get("updated_at"),
        "today_pnl": 0.0,
        "today_realized_r": float(realized_r),
        "positions_count": len(positions),
        "max_positions": effective.max_positions,
        "can_open_new_position": can_open,
        "risk_stop_reason": stop_reason or None,
    }


def trade_plan_list(
    session: Session,
    settings: Settings,
    *,
    status: str = "",
    symbol: str = "",
    priority: str = "",
    direction: str = "",
    active_only: bool = True,
) -> list[dict]:
    query = select(TradePlan)
    if active_only:
        query = query.where(TradePlan.status.in_(ACTIVE_PLAN_STATUSES))
    if status:
        query = query.where(TradePlan.status == status.upper())
    if symbol:
        query = query.where(TradePlan.symbol == symbol.upper())
    priorities = [value.strip().upper() for value in priority.split(",") if value.strip()]
    if priorities:
        query = query.where(TradePlan.priority_level.in_(priorities))
    if direction:
        query = query.where(TradePlan.direction == direction.upper())
    plans = list(session.scalars(query.order_by(TradePlan.updated_at.desc(), TradePlan.id.desc())))
    plans.sort(key=lambda plan: (_priority_rank(plan.priority_level), -plan.updated_at.timestamp(), -plan.id))
    return [_serialize_trade_plan(session, plan, settings) for plan in plans]


def trade_plan_detail(session: Session, plan: TradePlan, settings: Settings) -> dict:
    candidate = session.scalar(select(CandidateStock).where(CandidateStock.symbol == plan.symbol))
    structure = session.get(StructureEvent, plan.source_structure_id)
    battle = session.get(BattlePoolItem, plan.battle_pool_id)
    orders = list(
        session.scalars(
            select(SimOrder)
            .where(SimOrder.trade_plan_id == plan.id)
            .order_by(SimOrder.submitted_at.desc())
        )
    )
    position = session.scalar(
        select(Position)
        .where(Position.source_trade_plan_id == plan.id)
        .order_by(Position.updated_at.desc())
        .limit(1)
    )
    audit_logs = list(
        session.scalars(
            select(AuditLog)
            .where(AuditLog.subject_type == "TradePlan", AuditLog.subject_id == plan.id)
            .order_by(AuditLog.created_at.desc())
            .limit(50)
        )
    )
    serialized_plan = _serialize_trade_plan(session, plan, settings)
    return {
        "candidate": _candidate_payload(candidate),
        "structure_event": _structure_payload(structure),
        "battle_item": _battle_payload(battle),
        "trade_plan": serialized_plan,
        "realtime_checks": serialized_plan["checks"],
        "rules_approval_checks": {
            "status": plan.rules_approval_status,
            "display_name": label_for(plan.rules_approval_status),
            "reason": plan.rules_reject_reason,
        },
        "capital_checks": {
            "status": plan.capital_status,
            "display_name": label_for(plan.capital_status),
            "reason": plan.capital_reason,
            "available_cash_snapshot": plan.available_cash_snapshot,
            "max_new_position_value": plan.max_new_position_value,
        },
        "related_orders": [_serialize_order(order) for order in orders],
        "related_position": _serialize_position(position),
        "journal_summary": _journal_summary(position, orders),
        "audit_timeline": [_audit_payload(log) for log in audit_logs],
    }


def positions_payload(session: Session, symbol: str = "") -> list[dict]:
    query = select(Position)
    if symbol:
        query = query.where(Position.symbol == symbol.upper())
    positions = list(session.scalars(query.order_by(Position.updated_at.desc()).limit(300)))
    return [_serialize_position(position) for position in positions if position is not None]


def orders_payload(session: Session, symbol: str = "") -> list[dict]:
    query = select(SimOrder)
    if symbol:
        query = query.where(SimOrder.symbol == symbol.upper())
    orders = list(session.scalars(query.order_by(SimOrder.submitted_at.desc()).limit(300)))
    return [_serialize_order(order) for order in orders]


def kline_payload(session: Session, symbol: str, timeframe: str, limit: int = 300) -> dict:
    normalized_symbol = symbol.strip().upper()
    normalized_timeframe = timeframe.strip().lower()
    if not normalized_symbol:
        raise ValueError("股票代码不能为空")
    if normalized_timeframe not in TERMINAL_KLINE_TIMEFRAMES:
        raise ValueError("当前终端仅支持 1m、5m、15m、60m 和 1d K 线")
    bounded_limit = max(1, min(limit, 500))
    rows = list(
        session.scalars(
            select(KLine)
            .where(KLine.symbol == normalized_symbol, KLine.timeframe == normalized_timeframe)
            .order_by(KLine.ts.desc())
            .limit(bounded_limit)
        )
    )
    rows.reverse()
    return {
        "bars": [
            {
                "time": int(_as_utc(row.ts).timestamp()),
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "volume": row.volume,
            }
            for row in rows
            if row.data_ok
        ],
        "symbol": normalized_symbol,
        "timeframe": normalized_timeframe,
        "latest_bar_at": _iso(rows[-1].ts) if rows else None,
        "anomaly_count": sum(not row.data_ok for row in rows),
    }


def trade_plan_overlay_payload(session: Session, symbol: str, plan_id: int | None = None) -> dict:
    normalized_symbol = symbol.strip().upper()
    query = select(TradePlan).where(TradePlan.symbol == normalized_symbol)
    if plan_id is not None:
        query = query.where(TradePlan.id == plan_id)
    else:
        query = query.where(TradePlan.status.in_(ACTIVE_PLAN_STATUSES))
    plan = session.scalar(query.order_by(TradePlan.updated_at.desc(), TradePlan.id.desc()).limit(1))
    if plan is None:
        return {"symbol": normalized_symbol, "plan_id": None, "lines": []}
    raw_lines = [
        ("ENTRY", "计划入场价", plan.breakout_entry_price),
        ("NO_CHASE", "最高可接受价", plan.no_chase_above),
        ("STOP", "硬止损价", plan.stop_price),
        ("TARGET_1", "第一目标价", plan.target_1),
        ("TARGET_2", "第二目标价", plan.target_2),
        ("CURRENT", "当前价", plan.current_price),
    ]
    return {
        "symbol": normalized_symbol,
        "plan_id": plan.id,
        "lines": [
            {"type": line_type, "label": label, "price": float(price)}
            for line_type, label, price in raw_lines
            if price is not None
        ],
    }


def structures_payload(session: Session, symbol: str, timeframe: str = "60m", limit: int = 100) -> list[dict]:
    normalized_symbol = symbol.strip().upper()
    normalized_timeframe = timeframe.strip().lower()
    if normalized_timeframe not in TERMINAL_KLINE_TIMEFRAMES:
        raise ValueError("当前终端仅支持 60m 和 1d 结构查询")
    events = list(
        session.scalars(
            select(StructureEvent)
            .where(
                StructureEvent.symbol == normalized_symbol,
                StructureEvent.timeframe == normalized_timeframe,
            )
            .order_by(StructureEvent.event_ts.desc())
            .limit(max(1, min(limit, 300)))
        )
    )
    events.reverse()
    output = []
    for event in events:
        battle = session.scalar(select(BattlePoolItem).where(BattlePoolItem.source_structure_id == event.id))
        plan = session.scalar(
            select(TradePlan)
            .where(TradePlan.source_structure_id == event.id)
            .order_by(TradePlan.updated_at.desc())
            .limit(1)
        )
        payload = _structure_payload(event)
        payload.update({
            "linked_battle_item_id": battle.id if battle else None,
            "linked_trade_plan_id": plan.id if plan else None,
        })
        output.append(payload)
    return output


def response_envelope(data, *, source: str, synced_at=None) -> dict:
    return {
        "data": data,
        "meta": {
            "synced_at": _iso(synced_at) or datetime.now(UTC).isoformat(),
            "source": source,
            "stale": False,
        },
    }


def _serialize_trade_plan(session: Session, plan: TradePlan, settings: Settings) -> dict:
    view = plan_view_model(session, plan, settings)
    status = view["status"]
    return {
        "id": plan.id,
        "symbol": plan.symbol,
        "name": plan.name,
        "priority_level": plan.priority_level,
        "direction": plan.direction,
        "structure_type": plan.structure_type,
        "structure_display_name": label_for(plan.structure_type),
        "status": plan.status,
        "display_status": _status_payload(status),
        "current_price": plan.current_price,
        "current_change_pct": plan.current_change_pct,
        "entry_price": plan.breakout_entry_price,
        "no_chase_above": plan.no_chase_above,
        "stop_price": plan.stop_price,
        "target_1": plan.target_1,
        "target_2": plan.target_2,
        "risk_reward_1": plan.risk_reward_1,
        "risk_reward_2": plan.risk_reward_2,
        "capital_status": plan.capital_status,
        "capital_display_name": label_for(plan.capital_status),
        "rules_approval_status": plan.rules_approval_status,
        "rules_approval_display_name": label_for(plan.rules_approval_status),
        "primary_blocker": view["block_reason"] or None,
        "primary_blocker_reason": view["block_reason"] or None,
        "next_system_action": view["next_action"],
        "price_gate_status": view["price_gate_status"],
        "validation_status": view["validation_status"],
        "checks": view["checks"],
        "reason": plan.reason,
        "trailing_rule": plan.trailing_rule,
        "time_stop_rule": plan.time_stop_rule,
        "invalid_condition": plan.invalid_condition,
        "last_validated_at": _iso(plan.last_validated_at),
        "updated_at": _iso(plan.updated_at),
    }


def _serialize_position(position: Position | None) -> dict | None:
    if position is None:
        return None
    current_price = None
    if position.shares and position.risk_amount:
        current_price = position.entry_price + position.current_r * position.risk_amount / position.shares
    return {
        "id": position.id,
        "symbol": position.symbol,
        "direction": "LONG",
        "status": position.status,
        "entry_price": position.entry_price,
        "current_price": current_price,
        "current_r": position.current_r,
        "max_r": position.max_r,
        "min_r": position.min_r,
        "stop_price": position.stop_price,
        "target_1": position.target_1,
        "target_2": position.target_2,
        "partial_exit_done": position.partial_exit_done,
        "trailing_stop_price": position.trailing_stop_price,
        "next_system_action": describe_position_next_action(position),
        "exit_reason": position.exit_reason,
        "source_trade_plan_id": position.source_trade_plan_id,
        "entry_order_id": position.entry_order_id,
        "exit_order_id": position.exit_order_id,
        "shares": position.shares,
        "created_at": _iso(position.created_at),
        "updated_at": _iso(position.updated_at),
    }


def _serialize_order(order: SimOrder) -> dict:
    status = status_for(order.status)
    return {
        "id": order.id,
        "trade_plan_id": order.trade_plan_id,
        "symbol": order.symbol,
        "side": order.side,
        "qty": order.qty,
        "limit_price": order.limit_price,
        "filled_price": order.dealt_avg_price,
        "filled_qty": order.dealt_qty,
        "status": order.status,
        "display_status": _status_payload(status),
        "submitted_at": _iso(order.submitted_at),
        "filled_at": _iso(order.updated_at) if order.dealt_qty else None,
        "reason": order.reason,
    }


def _candidate_payload(candidate: CandidateStock | None) -> dict | None:
    if candidate is None:
        return None
    return {
        "id": candidate.id,
        "symbol": candidate.symbol,
        "name": candidate.name,
        "pool_type": candidate.pool_type,
        "pool_display_name": label_for(candidate.pool_type),
        "selected_reason": candidate.selected_reason,
        "rank_score": candidate.rank_score,
        "selected_at": _iso(candidate.selected_at),
    }


def _structure_payload(structure: StructureEvent | None) -> dict | None:
    if structure is None:
        return None
    return {
        "id": structure.id,
        "symbol": structure.symbol,
        "timeframe": structure.timeframe,
        "event_ts": _iso(structure.event_ts),
        "event_type": structure.event_type,
        "display_name": label_for(structure.event_type),
        "price": structure.price,
        "pivot_low": structure.pivot_low,
        "pivot_high": structure.pivot_high,
        "trigger_level": structure.trigger_level,
        "confirm_level": structure.confirm_level,
        "invalidation_level": structure.invalidation_level,
        "reason": structure.reason,
    }


def _battle_payload(battle: BattlePoolItem | None) -> dict | None:
    if battle is None:
        return None
    return {
        "id": battle.id,
        "symbol": battle.symbol,
        "direction": battle.direction,
        "priority_level": battle.priority_level,
        "daily_state": battle.daily_state,
        "structure_type": battle.structure_type,
        "score": battle.score,
        "reason": battle.reason,
        "next_wait": battle.next_wait,
        "status": battle.status,
    }


def _audit_payload(log: AuditLog) -> dict:
    return {
        "id": log.id,
        "time": _iso(log.created_at),
        "type": log.action,
        "title": label_for(log.action),
        "description": log.reason,
        "severity": log.status.lower(),
        "linked_entity_type": log.subject_type,
        "linked_entity_id": log.subject_id,
    }


def _journal_summary(position: Position | None, orders: list[SimOrder]) -> dict | None:
    if position:
        return {
            "status": "OPEN" if position.status == "OPEN" else "CLOSED",
            "summary": describe_position_next_action(position) if position.status == "OPEN" else position.exit_reason,
            "current_r": position.current_r,
        }
    if orders:
        latest = orders[0]
        return {
            "status": latest.status,
            "summary": latest.reason or status_for(latest.status).description,
            "current_r": None,
        }
    return None


def _status_payload(status: StatusPresentation) -> dict:
    return {
        "code": status.code,
        "display_name": status.display_name,
        "description": status.description,
        "severity": status.severity,
        "next_action": status.next_action,
    }


def _priority_rank(priority: str) -> int:
    return {"S": 0, "A": 1, "B": 2, "C": 3}.get(priority, 4)


def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        aware = _as_utc(value)
        return aware.isoformat()
    return str(value)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
