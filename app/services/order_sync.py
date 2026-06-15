import json
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Position, SimDeal, SimOrder, TradePlan
from app.services.audit import write_audit
from app.services.position_sync import normalize_symbol


OPEN_STATUSES = {"SUBMITTED", "SUBMITTING", "WAITING_SUBMIT", "PARTIALLY_FILLED", "PART_FILLED"}
FILLED_STATUSES = {"FILLED", "FILLED_ALL"}
CANCELLED_STATUSES = {"CANCELLED", "CANCELLED_ALL", "CANCELLED_PART"}
FAILED_STATUSES = {"FAILED", "DISABLED", "DELETED"}


def sync_sim_orders(session: Session, trade_provider, timeout_seconds: int = 60) -> dict[str, int]:
    rows = trade_provider.get_open_orders()
    deals_supported = True
    try:
        deals = trade_provider.get_deals()
    except RuntimeError as exc:
        if "模拟交易不支持成交数据" not in str(exc):
            raise
        deals = []
        deals_supported = False
    updated = filled = 0
    by_id = {str(row.get("order_id") or ""): row for row in rows}
    for order in session.scalars(select(SimOrder).where(SimOrder.status.in_({"SUBMITTED", "PARTIALLY_FILLED"}))):
        row = by_id.get(order.futu_order_id)
        if row:
            status = _normalize_status(str(row.get("order_status") or row.get("status") or ""))
            order.status = status
            order.dealt_qty = int(float(row.get("dealt_qty") or 0))
            order.dealt_avg_price = float(row.get("dealt_avg_price") or 0) or None
            order.raw_response_json = json.dumps(row, ensure_ascii=False, default=str)
            updated += 1
            if status == "FILLED":
                _open_or_close_position(session, order)
                filled += 1
                continue
            if status in {"CANCELLED", "FAILED"}:
                continue
        if order.status == "SUBMITTED" and order.submitted_at < datetime.utcnow() - timedelta(seconds=timeout_seconds):
            try:
                trade_provider.cancel_order(order.futu_order_id)
            except Exception as exc:
                if _is_missing_remote_order(exc):
                    _mark_cancelled(session, order, "Futu 已不存在该订单，本地停止重复撤单")
                else:
                    order.reason = str(exc)
            else:
                _mark_cancelled(session, order, "入场限价单超过等待时间")
            continue

    known_deals = {deal.futu_deal_id for deal in session.scalars(select(SimDeal))}
    for row in deals:
        deal_id = str(row.get("deal_id") or "")
        if not deal_id or deal_id in known_deals:
            continue
        order = session.scalar(select(SimOrder).where(SimOrder.futu_order_id == str(row.get("order_id") or "")))
        if not order:
            continue
        session.add(
            SimDeal(
                sim_order_id=order.id,
                symbol=order.symbol,
                side=order.side,
                qty=int(float(row.get("qty") or 0)),
                price=float(row.get("price") or 0),
                dealt_at=datetime.utcnow(),
                futu_deal_id=deal_id,
                raw_json=json.dumps(row, ensure_ascii=False, default=str),
            )
        )
    session.commit()
    return {"updated": updated, "filled": filled, "deals_supported": deals_supported}


def _mark_cancelled(session: Session, order: SimOrder, reason: str) -> None:
    order.status = "CANCELLED"
    order.reason = reason
    if order.trade_plan_id:
        plan = session.get(TradePlan, order.trade_plan_id)
        if plan:
            plan.status = "ARMED"
    write_audit(
        session,
        "SIM_ORDER_CANCELLED",
        symbol=order.symbol,
        subject_type="SimOrder",
        subject_id=order.id,
        reason=reason,
    )


def _is_missing_remote_order(exc: Exception) -> bool:
    message = str(exc)
    return "订单号不存在" in message or "order does not exist" in message.lower()


def _open_or_close_position(session: Session, order: SimOrder) -> None:
    plan = session.get(TradePlan, order.trade_plan_id) if order.trade_plan_id else None
    if order.side == "BUY" and plan:
        symbol = normalize_symbol(order.symbol)
        position = session.scalar(
            select(Position).where(Position.symbol.in_({symbol, symbol.removeprefix("US.")}))
        )
        if position is None:
            position = Position(
                symbol=symbol,
                entry_signal_id=None,
                entry_price=order.dealt_avg_price or order.limit_price,
                stop_price=plan.stop_price,
                shares=order.dealt_qty or order.qty,
                risk_amount=(order.dealt_avg_price or order.limit_price - plan.stop_price) * (order.dealt_qty or order.qty),
                available_shares=order.dealt_qty or order.qty,
                source="LOCAL_STRATEGY",
            )
            session.add(position)
        else:
            position.symbol = symbol
        position.status = "OPEN"
        position.source_trade_plan_id = plan.id
        position.entry_order_id = order.id
        position.target_1 = plan.target_1
        position.target_2 = plan.target_2
        position.overnight_policy = "INTRADAY_ONLY"
        plan.status = "IN_POSITION"
        write_audit(session, "POSITION_OPENED", symbol=order.symbol, subject_type="Position", status="OPEN")
    elif order.side == "SELL":
        symbol = normalize_symbol(order.symbol)
        position = session.scalar(
            select(Position).where(
                Position.symbol.in_({symbol, symbol.removeprefix("US.")}),
                Position.status == "OPEN",
            )
        )
        if position:
            sold = order.dealt_qty or order.qty
            position.shares = max(0, position.shares - sold)
            position.available_shares = max(0, position.available_shares - sold)
            if position.shares == 0:
                position.status = "CLOSED"
                position.exit_order_id = order.id
                write_audit(session, "POSITION_CLOSED", symbol=order.symbol, subject_type="Position", subject_id=position.id)


def _normalize_status(value: str) -> str:
    upper = value.upper()
    if upper in FILLED_STATUSES:
        return "FILLED"
    if upper in CANCELLED_STATUSES:
        return "CANCELLED"
    if upper in FAILED_STATUSES:
        return "FAILED"
    if "PART" in upper:
        return "PARTIALLY_FILLED"
    return "SUBMITTED"
