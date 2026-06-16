import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Position, SimOrder
from app.services.audit import write_audit
from app.services.position_sync import normalize_symbol


logger = logging.getLogger(__name__)

EXIT_RETRY_REASONS = {
    "HARD_STOP",
    "ORPHAN_TAKE_PROFIT",
    "TARGET_2_OR_TRAILING",
    "FORCED_INTRADAY_EXIT",
    "TARGET_1_PARTIAL",
}


def manage_positions(session: Session, quote_provider, trade_provider, settings: Settings) -> dict[str, int]:
    positions = list(session.scalars(select(Position).where(Position.status == "OPEN")))
    snapshots = quote_provider.get_market_snapshot([position.symbol for position in positions]) if positions else []
    by_symbol = {
        normalize_symbol(row.get("code") or row.get("symbol")): row
        for row in snapshots
    }
    submitted = errors = skipped = 0
    for position in positions:
        try:
            outcome = _manage_position(
                session,
                position,
                by_symbol.get(normalize_symbol(position.symbol)),
                trade_provider,
                settings,
            )
            submitted += int(outcome == "SUBMITTED")
            skipped += int(outcome == "SKIPPED")
            errors += int(outcome == "ERROR")
        except Exception as exc:
            errors += 1
            position.last_error = str(exc)
            position.last_risk_checked_at = datetime.now(UTC).replace(tzinfo=None)
            logger.exception("[RISK] %s 持仓检查失败，继续处理其他持仓", position.symbol)
            write_audit(
                session,
                "POSITION_RISK_CHECK_FAILED",
                symbol=position.symbol,
                subject_type="Position",
                subject_id=position.id,
                status="FAILED",
                reason=str(exc),
            )
            session.commit()
    return {
        "managed": len(positions),
        "exit_orders_submitted": submitted,
        "errors": errors,
        "skipped": skipped,
    }


def _manage_position(
    session: Session,
    position: Position,
    snapshot: dict | None,
    trade_provider,
    settings: Settings,
) -> str:
    now = datetime.now(UTC).replace(tzinfo=None)
    current = _snapshot_price(snapshot) or float(position.current_price or 0)
    if current <= 0:
        raise RuntimeError("无法读取持仓当前价")
    position.current_price = current
    position.market_value = current * position.shares
    position.unrealized_pnl = (current - position.entry_price) * position.shares
    position.unrealized_pnl_pct = (
        (current - position.entry_price) / position.entry_price
        if position.entry_price > 0
        else 0
    )
    position.last_risk_checked_at = now
    position.last_error = ""

    stop_pct = position.stop_loss_pct or settings.orphan_stop_loss_pct
    take_pct = position.take_profit_pct or settings.orphan_take_profit_pct
    if position.is_orphan:
        position.stop_price = position.entry_price * (1 - stop_pct)
        position.target_1 = position.entry_price * (1 + take_pct)

    risk = max(position.entry_price - position.stop_price, 0.0001)
    position.current_r = (current - position.entry_price) / risk
    position.max_r = max(position.max_r, position.current_r)
    position.min_r = min(position.min_r, position.current_r)
    logger.info(
        "[RISK] 检查 %s：成本价 %.4f，现价 %.4f，收益率 %.2f%%",
        position.symbol,
        position.entry_price,
        current,
        position.unrealized_pnl_pct * 100,
    )

    quantity = 0
    reason = ""
    hard_stop = max(position.stop_price, position.trailing_stop_price or 0)
    if current <= hard_stop:
        quantity, reason = position.available_shares, "HARD_STOP"
        logger.warning("[RISK] %s 达到止损线，准备卖出", position.symbol)
    elif position.is_orphan and position.unrealized_pnl_pct >= take_pct:
        quantity, reason = position.available_shares, "ORPHAN_TAKE_PROFIT"
        logger.info("[RISK] %s 达到默认止盈线，准备卖出", position.symbol)
    elif position.target_2 and current >= position.target_2:
        quantity, reason = position.available_shares, "TARGET_2_OR_TRAILING"
    elif position.target_1 and current >= position.target_1 and not position.partial_exit_done:
        quantity = min(position.available_shares, max(1, position.shares // 2))
        reason = "TARGET_1_PARTIAL"
    elif position.current_r >= 1.5:
        position.trailing_stop_price = max(
            position.trailing_stop_price or position.stop_price,
            position.entry_price + 0.5 * risk,
        )
        write_audit(
            session,
            "TRAILING_STOP_UPDATED",
            symbol=position.symbol,
            subject_type="Position",
            subject_id=position.id,
            payload={"trailing_stop": position.trailing_stop_price, "current_r": position.current_r},
        )
    if settings.force_intraday_exit and _near_close():
        quantity, reason = position.available_shares, "FORCED_INTRADAY_EXIT"

    if not reason:
        session.commit()
        return "HELD"
    if position.available_shares <= 0 or quantity <= 0:
        message = "position exists but sellable_qty = 0, skip exit order"
        position.last_error = message
        logger.warning("[SKIP] %s 可卖数量为 0，跳过卖出", position.symbol)
        write_audit(
            session,
            "POSITION_EXIT_SKIPPED",
            symbol=position.symbol,
            subject_type="Position",
            subject_id=position.id,
            status="SKIPPED",
            reason=message,
        )
        session.commit()
        return "SKIPPED"
    active_order = _active_exit_order_exists(session, position)
    if active_order:
        session.commit()
        return "HELD"
    retry_order = _retryable_waiting_exit_order(session, position, settings)
    if retry_order:
        if not _remote_or_recent_position_exists(trade_provider, position):
            session.commit()
            return "HELD"
        next_retry_count = (retry_order.retry_count or 0) + 1
        if next_retry_count > settings.max_exit_order_retries:
            message = "风控退出单达到最大重试次数，需要人工检查富途账户"
            if position.last_error != message:
                position.last_error = message
                write_audit(
                    session,
                    "EXIT_ORDER_RETRY_LIMIT_REACHED",
                    symbol=position.symbol,
                    subject_type="Position",
                    subject_id=position.id,
                    status="FAILED",
                    reason=message,
                    payload={
                        "previous_order_id": retry_order.id,
                        "previous_futu_order_id": retry_order.futu_order_id,
                        "retry_count": retry_order.retry_count or 0,
                    },
                )
            session.commit()
            return "HELD"
    elif _waiting_exit_order_before_retry_window(session, position, settings):
        session.commit()
        return "HELD"

    try:
        exit_price = _exit_limit_price(snapshot, current)
        response = trade_provider.place_simulated_order(position.symbol, "SELL", quantity, exit_price)
        order = SimOrder(
            trade_plan_id=position.source_trade_plan_id,
            symbol=position.symbol,
            side="SELL",
            qty=quantity,
            limit_price=exit_price,
            submitted_price=exit_price,
            futu_order_id=str(response.get("order_id") or ""),
            status="SUBMITTED",
            reason=reason,
            retry_count=next_retry_count if retry_order else 0,
        )
        session.add(order)
        position.exit_reason = reason
        logger.info(
            "[ORDER] %s 卖出委托已提交，数量 %s，订单号 %s",
            position.symbol,
            quantity,
            order.futu_order_id,
        )
        write_audit(
            session,
            "STOP_LOSS_TRIGGERED" if reason == "HARD_STOP" else "TAKE_PROFIT_TRIGGERED",
            symbol=position.symbol,
            subject_type="Position",
            subject_id=position.id,
            reason=reason,
            payload={"price": exit_price, "last_price": current, "qty": quantity, "futu_order_id": order.futu_order_id},
        )
        if retry_order:
            write_audit(
                session,
                "EXIT_ORDER_RETRIED",
                symbol=position.symbol,
                subject_type="Position",
                subject_id=position.id,
                payload={
                    "previous_order_id": retry_order.id,
                    "previous_futu_order_id": retry_order.futu_order_id,
                    "retry_count": next_retry_count,
                    "qty": quantity,
                    "exit_price": exit_price,
                    "exit_reason": reason,
                },
            )
        session.commit()
        return "SUBMITTED"
    except Exception as exc:
        logger.exception("[ORDER] %s 卖出失败，原因 %s", position.symbol, exc)
        position.last_error = str(exc)
        write_audit(
            session,
            "POSITION_EXIT_ORDER_FAILED",
            symbol=position.symbol,
            subject_type="Position",
            subject_id=position.id,
            status="FAILED",
            reason=str(exc),
            payload={"price": current, "qty": quantity, "exit_reason": reason},
        )
        session.commit()
        return "ERROR"


def _snapshot_price(row: dict | None) -> float:
    if not row:
        return 0
    try:
        return float(row.get("last_price") or row.get("cur_price") or row.get("nominal_price") or 0)
    except (TypeError, ValueError):
        return 0


def _exit_limit_price(row: dict | None, current: float) -> float:
    bid = 0.0
    if row:
        try:
            bid = float(row.get("bid_price") or row.get("bid_price_1") or 0)
        except (TypeError, ValueError):
            bid = 0.0
    reference = bid if bid > 0 else current * 0.995
    return round(max(reference, 0.01), 2)


def _active_exit_order_exists(session: Session, position: Position) -> SimOrder | None:
    aliases = _symbol_aliases(position.symbol)
    return session.scalar(
        select(SimOrder)
        .where(
            SimOrder.symbol.in_(aliases),
            SimOrder.side == "SELL",
            SimOrder.status.in_({"SUBMITTED", "PARTIALLY_FILLED"}),
        )
        .order_by(SimOrder.submitted_at.desc(), SimOrder.id.desc())
        .limit(1)
    )


def _retryable_waiting_exit_order(session: Session, position: Position, settings: Settings) -> SimOrder | None:
    aliases = _symbol_aliases(position.symbol)
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=settings.sell_reconcile_retry_seconds)
    candidates = session.scalars(
        select(SimOrder)
        .where(
            SimOrder.symbol.in_(aliases),
            SimOrder.side == "SELL",
            SimOrder.status == "SELL_WAITING_RECONCILIATION",
            SimOrder.submitted_at <= cutoff,
        )
        .order_by(SimOrder.submitted_at.desc(), SimOrder.id.desc())
    )
    for order in candidates:
        if _exit_reason_retryable(order.reason) or position.exit_reason in EXIT_RETRY_REASONS:
            return order
    return None


def _waiting_exit_order_before_retry_window(session: Session, position: Position, settings: Settings) -> bool:
    aliases = _symbol_aliases(position.symbol)
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=settings.sell_reconcile_retry_seconds)
    return bool(
        session.scalar(
            select(SimOrder.id)
            .where(
                SimOrder.symbol.in_(aliases),
                SimOrder.side == "SELL",
                SimOrder.status == "SELL_WAITING_RECONCILIATION",
                SimOrder.submitted_at > cutoff,
            )
            .limit(1)
        )
    )


def _remote_or_recent_position_exists(trade_provider, position: Position) -> bool:
    try:
        rows = trade_provider.get_positions()
    except AttributeError:
        return position.shares > 0
    except Exception:
        return position.shares > 0 and position.last_synced_at is not None
    aliases = _symbol_aliases(position.symbol)
    for row in rows:
        symbol = normalize_symbol(row.get("code") or row.get("symbol"))
        try:
            quantity = int(float(row.get("qty") or row.get("quantity") or 0))
        except (TypeError, ValueError):
            quantity = 0
        if symbol in aliases and quantity > 0:
            return True
    return position.shares > 0 and position.last_synced_at is not None


def _symbol_aliases(symbol: str) -> set[str]:
    normalized = normalize_symbol(symbol)
    return {normalized, normalized.removeprefix("US.")}


def _exit_reason_retryable(reason: str | None) -> bool:
    text = reason or ""
    return any(item in text for item in EXIT_RETRY_REASONS)


def _near_close(now: datetime | None = None) -> bool:
    now = now or datetime.now(ZoneInfo("America/New_York"))
    return now.weekday() < 5 and (now.hour, now.minute) >= (15, 45)
