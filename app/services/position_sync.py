import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Position, SimOrder, TradePlan
from app.services.audit import write_audit


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OrderMatchResult:
    order: SimOrder | None
    confidence: str
    reason: str
    candidates: list[SimOrder]


def sync_futu_positions_to_local(
    session: Session,
    trade_provider,
    settings: Settings,
) -> dict[str, int]:
    rows = trade_provider.get_positions()
    logger.info("[SYNC] 从富途读取到 %s 个持仓", len(rows))
    seen: set[str] = set()
    created = updated = closed = 0
    now = datetime.now(UTC).replace(tzinfo=None)

    for row in rows:
        quantity = _int_value(row.get("qty") or row.get("quantity"))
        if quantity <= 0:
            continue
        symbol = normalize_symbol(row.get("code") or row.get("symbol"))
        if not symbol:
            continue
        seen.add(symbol)
        cost = _float_value(row.get("cost_price") or row.get("average_price"))
        market_value = _float_value(row.get("market_val") or row.get("market_value"))
        current = _float_value(
            row.get("nominal_price")
            or row.get("current_price")
            or row.get("last_price")
        )
        if current <= 0 and quantity > 0 and market_value > 0:
            current = market_value / quantity
        pnl = _float_value(row.get("pl_val") or row.get("pl_value"))
        pnl_pct = (current - cost) / cost if current > 0 and cost > 0 else _ratio_value(row.get("pl_ratio"))
        available = _int_value(
            _first_present(row, "can_sell_qty", "available_qty", default=quantity)
        )
        logger.info(
            "[SYNC] 发现富途持仓：%s，数量 %s，成本价 %.4f，现价 %.4f",
            symbol,
            quantity,
            cost,
            current,
        )

        aliases = {symbol, symbol.removeprefix("US.")}
        position = session.scalar(select(Position).where(Position.symbol.in_(aliases)))
        match = _matching_unresolved_buy_order(session, aliases, quantity, cost, now, settings)
        matching_buy_order = match.order
        if position is None:
            position = Position(
                symbol=symbol,
                status="OPEN",
                entry_signal_id=0,
                entry_price=cost,
                stop_price=cost * (1 - settings.orphan_stop_loss_pct),
                shares=quantity,
                risk_amount=cost * settings.orphan_stop_loss_pct * quantity,
                source="LOCAL_AND_FUTU_CONFIRMED" if matching_buy_order else "FUTU_DETECTED",
                is_orphan=matching_buy_order is None,
                source_trade_plan_id=matching_buy_order.trade_plan_id if matching_buy_order else None,
                entry_order_id=matching_buy_order.id if matching_buy_order else None,
                take_profit_pct=settings.orphan_take_profit_pct,
                stop_loss_pct=settings.orphan_stop_loss_pct,
                target_1=cost * (1 + settings.orphan_take_profit_pct),
                overnight_policy="FUTU_ACCOUNT",
            )
            session.add(position)
            session.flush()
            created += 1
            if matching_buy_order:
                matching_buy_order.status = "FILLED_INFERRED"
                matching_buy_order.dealt_qty = quantity
                matching_buy_order.dealt_avg_price = cost
                if matching_buy_order.trade_plan_id:
                    plan = session.get(TradePlan, matching_buy_order.trade_plan_id)
                    if plan:
                        plan.status = "IN_POSITION"
                logger.warning("[SYNC] 本地不存在 %s 持仓，但匹配到入场订单，创建 confirmed position", symbol)
                write_audit(
                    session,
                    "SIM_ORDER_FILLED_INFERRED",
                    symbol=symbol,
                    subject_type="SimOrder",
                    subject_id=matching_buy_order.id,
                    status="FILLED_INFERRED",
                    reason="Futu 持仓存在，推断入场订单已成交",
                    payload={
                        "match_confidence": match.confidence,
                        "match_reason": match.reason,
                        "remote_qty": quantity,
                        "remote_cost": cost,
                        "order_qty": matching_buy_order.qty,
                        "order_limit_price": matching_buy_order.limit_price,
                        "order_submitted_at": matching_buy_order.submitted_at.isoformat()
                        if matching_buy_order.submitted_at
                        else "",
                    },
                )
            else:
                logger.warning("[SYNC] 本地不存在 %s 持仓，创建 orphan position", symbol)
                if match.candidates:
                    write_audit(
                        session,
                        "ORPHAN_POSITION_MATCH_LOW_CONFIDENCE",
                        symbol=symbol,
                        subject_type="Position",
                        subject_id=position.id,
                        status="WARNING",
                        reason="Futu 持仓存在，但本地存在多个或低置信未完成 BUY 单，未自动绑定",
                        payload={
                            "symbol": symbol,
                            "remote_qty": quantity,
                            "remote_cost": cost,
                            "candidate_order_ids": [order.id for order in match.candidates],
                            "match_reason": match.reason,
                        },
                    )
            write_audit(
                session,
                "ORPHAN_POSITION_DETECTED",
                symbol=symbol,
                subject_type="Position",
                subject_id=position.id,
                status="OPEN",
                reason=(
                    "Futu 模拟账户存在持仓，已反向绑定本地入场订单"
                    if matching_buy_order
                    else "Futu 模拟账户存在持仓，但本地没有对应持仓记录"
                ),
            )
        else:
            updated += 1
            position.symbol = symbol
            position.source = (
                "LOCAL_AND_FUTU_CONFIRMED"
                if position.source_trade_plan_id or position.entry_order_id
                else "FUTU_DETECTED"
            )
            if not position.source_trade_plan_id and not position.entry_order_id:
                position.is_orphan = True
        position.status = "OPEN"
        position.name = str(row.get("stock_name") or row.get("name") or position.name or "")
        position.shares = quantity
        position.available_shares = max(available, 0)
        position.entry_price = cost or position.entry_price
        position.current_price = current or position.current_price
        position.market_value = market_value or current * quantity
        position.unrealized_pnl = pnl
        position.unrealized_pnl_pct = pnl_pct
        position.last_synced_at = now
        position.last_error = ""
        if position.is_orphan:
            position.take_profit_pct = position.take_profit_pct or settings.orphan_take_profit_pct
            position.stop_loss_pct = position.stop_loss_pct or settings.orphan_stop_loss_pct
            position.stop_price = position.entry_price * (1 - position.stop_loss_pct)
            position.target_1 = position.entry_price * (1 + position.take_profit_pct)

    local_open = list(session.scalars(select(Position).where(Position.status == "OPEN")))
    for position in local_open:
        if position.symbol in seen:
            continue
        if position.source in {"FUTU_DETECTED", "LOCAL_AND_FUTU_CONFIRMED"}:
            filled_sell_order = _filled_sell_order(session, position)
            if filled_sell_order:
                _mark_verified_closed_from_sell_order(position, filled_sell_order, now)
                status = "CLOSED"
                action = "POSITION_RECONCILED_CLOSED"
                reason = "Futu 模拟账户已无该持仓，且本地 SELL 成交已确认"
            else:
                position.status = "CLOSED_UNVERIFIED"
                position.exit_price = None
                position.realized_pnl = None
                position.close_verified = False
                position.close_source = "REMOTE_POSITION_MISSING"
                status = "CLOSED_UNVERIFIED"
                action = "POSITION_RECONCILED_CLOSED_UNVERIFIED"
                reason = "Futu 模拟账户已无该持仓，但本地未确认 SELL 成交"
            position.exit_reason = position.exit_reason or "FUTU_POSITION_NO_LONGER_PRESENT"
            position.available_shares = 0
            position.last_synced_at = now
            closed += 1
            plan = session.get(TradePlan, position.source_trade_plan_id) if position.source_trade_plan_id else None
            if plan and plan.status == "IN_POSITION":
                plan.status = "COOLDOWN"
            write_audit(
                session,
                action,
                symbol=position.symbol,
                subject_type="Position",
                subject_id=position.id,
                status=status,
                reason=reason,
            )

    session.commit()
    return {"remote": len(rows), "created": created, "updated": updated, "closed": closed}


def normalize_symbol(value) -> str:
    symbol = str(value or "").strip().upper()
    if not symbol:
        return ""
    return symbol if "." in symbol else f"US.{symbol}"


def _matching_unresolved_buy_order(
    session: Session,
    aliases: set[str],
    remote_quantity: int,
    remote_cost: float,
    now: datetime,
    settings: Settings,
) -> OrderMatchResult:
    candidates = list(
        session.scalars(
            select(SimOrder)
            .where(
                SimOrder.symbol.in_(aliases),
                SimOrder.side == "BUY",
                SimOrder.status.in_({"SUBMITTED", "PARTIALLY_FILLED", "UNKNOWN_REMOTE_MISSING"}),
            )
            .order_by(SimOrder.submitted_at.desc(), SimOrder.id.desc())
        )
    )
    if not candidates:
        return OrderMatchResult(None, "NONE", "没有本地未完成 BUY 候选订单", [])
    if len(candidates) > 1:
        return OrderMatchResult(None, "LOW", "存在多个同标的未完成 BUY 候选订单，避免误绑定", candidates)
    order = candidates[0]
    expected_qty = order.dealt_qty or order.qty
    qty_tolerance = max(1, remote_quantity * 0.05)
    qty_match = abs(expected_qty - remote_quantity) <= qty_tolerance
    reference_price = order.dealt_avg_price or order.limit_price or order.submitted_price
    price_available = remote_cost > 0 and bool(reference_price)
    price_match = bool(price_available and abs(reference_price - remote_cost) / remote_cost <= 0.03)
    time_match = bool(
        order.submitted_at
        and (
            order.submitted_at.date() == now.date()
            or order.submitted_at >= now - timedelta(minutes=settings.buy_order_match_window_minutes)
        )
    )
    if qty_match and price_match and time_match:
        return OrderMatchResult(order, "HIGH", "数量、价格和提交时间均匹配", candidates)
    if qty_match and time_match and not price_available:
        return OrderMatchResult(order, "MEDIUM", "数量和提交时间匹配，远端成本价或订单价格不可用", candidates)
    misses = []
    if not qty_match:
        misses.append("数量不匹配")
    if price_available and not price_match:
        misses.append("价格偏差超过阈值")
    if not price_available:
        misses.append("价格数据不可用")
    if not time_match:
        misses.append("订单提交时间超出匹配窗口")
    return OrderMatchResult(None, "LOW", "；".join(misses) or "低置信匹配", candidates)


def _filled_sell_order(session: Session, position: Position) -> SimOrder | None:
    aliases = {normalize_symbol(position.symbol), normalize_symbol(position.symbol).removeprefix("US.")}
    return session.scalar(
        select(SimOrder)
        .where(
            SimOrder.symbol.in_(aliases),
            SimOrder.side == "SELL",
            SimOrder.status.in_({"FILLED", "FILLED_INFERRED"}),
        )
        .order_by(SimOrder.submitted_at.desc(), SimOrder.id.desc())
        .limit(1)
    )


def _mark_verified_closed_from_sell_order(position: Position, order: SimOrder, now: datetime) -> None:
    sold = order.dealt_qty or order.qty
    exit_price = order.dealt_avg_price or order.limit_price
    position.status = "CLOSED"
    position.exit_order_id = order.id
    position.exit_price = exit_price
    position.realized_pnl = (exit_price - position.entry_price) * sold
    position.close_verified = True
    position.close_source = "SELL_ORDER_FILLED"
    position.shares = 0
    position.available_shares = 0
    position.last_synced_at = now


def _float_value(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _int_value(value) -> int:
    return int(_float_value(value))


def _ratio_value(value) -> float:
    ratio = _float_value(value)
    return ratio / 100 if abs(ratio) > 1 else ratio


def _first_present(row: dict, *keys: str, default=None):
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return default
