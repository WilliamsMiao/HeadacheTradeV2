import json
from datetime import UTC, datetime
from typing import Any, NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Position, ReconciliationIssue, SimOrder
from app.services.position_sync import normalize_symbol


MANAGED_ISSUE_TYPES = {
    "REMOTE_POSITION_WITHOUT_LOCAL",
    "LOCAL_POSITION_MISSING_REMOTE",
    "REMOTE_ORDER_WITHOUT_LOCAL",
    "LOCAL_ORDER_MISSING_REMOTE",
    "POSITION_QTY_MISMATCH",
    "POSITION_COST_MISMATCH",
    "SELL_ORDER_STUCK",
    "BUY_ORDER_INFERRED_FILLED",
    "CLOSE_UNVERIFIED",
    "ORDER_STATUS_UNKNOWN",
    "ACCOUNT_SYNC_FAILED",
    "RECONCILIATION_RUN_FAILED",
}
RECONCILE_ORDER_STATUSES = {
    "SUBMITTED",
    "PARTIALLY_FILLED",
    "UNKNOWN_REMOTE_MISSING",
    "SELL_WAITING_RECONCILIATION",
}
BLOCKING_SEVERITIES = {"HIGH", "CRITICAL"}
SEVERITY_RANK = {"INFO": 0, "WARN": 1, "HIGH": 2, "CRITICAL": 3}


class IssueKey(NamedTuple):
    issue_type: str
    symbol: str
    remote_order_id: str
    local_order_id: int | None
    position_id: int | None
    trade_plan_id: int | None


def run_trade_reconciliation(session: Session, trade_provider, settings: Settings) -> dict[str, object]:
    del settings
    now = datetime.now(UTC).replace(tzinfo=None)
    seen: set[IssueKey] = set()
    opened = 0

    try:
        remote_positions = trade_provider.get_positions()
        remote_orders = trade_provider.get_open_orders()
        deals_supported = True
        try:
            remote_deals = trade_provider.get_deals()
        except RuntimeError as exc:
            if "模拟交易不支持成交数据" not in str(exc):
                raise
            remote_deals = []
            deals_supported = False
    except Exception as exc:
        issue, created = _upsert_issue(
            session,
            now=now,
            issue_type="ACCOUNT_SYNC_FAILED",
            severity="CRITICAL",
            reason=f"账户同步失败：{exc}",
            payload={"error": str(exc)},
        )
        seen.add(_issue_key(issue))
        opened += int(created)
        session.commit()
        return _health_payload(session, opened, 0, deals_supported=False, reason="账户同步失败，需要人工检查")

    remote_positions_by_symbol = _remote_positions_by_symbol(remote_positions)
    remote_order_ids = {str(row.get("order_id") or "") for row in remote_orders if row.get("order_id")}
    remote_deal_order_ids = {str(row.get("order_id") or "") for row in remote_deals if row.get("order_id")}

    opened += _check_remote_positions_without_local(session, now, seen, remote_positions_by_symbol)
    opened += _check_local_positions(session, now, seen, remote_positions_by_symbol)
    opened += _check_remote_orders_without_local(session, now, seen, remote_orders)
    opened += _check_local_orders(session, now, seen, remote_order_ids, remote_deal_order_ids)
    opened += _check_closed_unverified(session, now, seen)
    opened += _check_inferred_buy_orders(session, now, seen)

    resolved = resolve_stale_issues(session, seen, now=now)
    session.commit()
    return _health_payload(session, opened, resolved, deals_supported=deals_supported)


def save_reconciliation_gate_status(session: Session, reconciliation: dict[str, object]) -> dict[str, object]:
    from app.models import SystemConfig

    payload = {
        "allow_new_entries": bool(reconciliation.get("allow_new_entries")),
        "severity": str(reconciliation.get("severity") or "INFO"),
        "mode": _gate_mode(
            bool(reconciliation.get("allow_new_entries")),
            str(reconciliation.get("severity") or "INFO"),
            str(reconciliation.get("reason") or ""),
        ),
        "reason": str(reconciliation.get("reason") or ""),
        "open_issues": int(reconciliation.get("open_issues") or 0),
        "high_issues": int(reconciliation.get("high_issues") or 0),
        "critical_issues": int(reconciliation.get("critical_issues") or 0),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    record = session.scalar(select(SystemConfig).where(SystemConfig.key == "reconciliation_gate_status"))
    if record is None:
        record = SystemConfig(key="reconciliation_gate_status")
        session.add(record)
    record.value = json.dumps(payload, ensure_ascii=False, default=str)
    session.commit()
    return payload


def save_reconciliation_gate_failure(session: Session, reason: str) -> dict[str, object]:
    from app.services.audit import write_audit

    now = datetime.now(UTC).replace(tzinfo=None)
    issue, _created = _upsert_issue(
        session,
        now=now,
        issue_type="RECONCILIATION_RUN_FAILED",
        severity="CRITICAL",
        reason=reason,
        payload={"error": reason},
    )
    write_audit(
        session,
        "RECONCILIATION_RUN_FAILED",
        subject_type="ReconciliationIssue",
        subject_id=issue.id,
        status="FAILED",
        reason=reason,
    )
    payload = save_reconciliation_gate_status(
        session,
        {
            "allow_new_entries": False,
            "severity": "CRITICAL",
            "open_issues": 1,
            "high_issues": 0,
            "critical_issues": 1,
            "reason": reason,
        },
    )
    return payload


def reconciliation_gate_status(session: Session) -> dict[str, object] | None:
    from app.models import SystemConfig

    record = session.scalar(select(SystemConfig).where(SystemConfig.key == "reconciliation_gate_status"))
    if record:
        try:
            payload = json.loads(record.value)
        except json.JSONDecodeError:
            return {
                "allow_new_entries": False,
                "severity": "CRITICAL",
                "mode": "SYNC_FAILED",
                "reason": "交易对账闸门状态损坏，禁止新开仓",
                "open_issues": 0,
                "high_issues": 0,
                "critical_issues": 1,
                "updated_at": None,
            }
        return _normalize_gate_payload(payload)
    open_issues = list(session.scalars(select(ReconciliationIssue).where(ReconciliationIssue.status == "OPEN")))
    if not open_issues:
        return None
    severity = _max_severity(issue.severity for issue in open_issues)
    critical_issues = sum(issue.severity == "CRITICAL" for issue in open_issues)
    high_issues = sum(issue.severity == "HIGH" for issue in open_issues)
    allow_new_entries = critical_issues == 0 and high_issues == 0
    reason = _health_reason(severity)
    return {
        "allow_new_entries": allow_new_entries,
        "severity": severity,
        "mode": _gate_mode(allow_new_entries, severity, reason),
        "reason": reason,
        "open_issues": len(open_issues),
        "high_issues": high_issues,
        "critical_issues": critical_issues,
        "updated_at": max((issue.last_seen_at for issue in open_issues if issue.last_seen_at), default=None),
    }


def upsert_issue(
    session: Session,
    *,
    issue_type: str,
    symbol: str = "",
    severity: str = "WARN",
    reason: str = "",
    remote_order_id: str = "",
    local_order_id: int | None = None,
    position_id: int | None = None,
    trade_plan_id: int | None = None,
    payload: dict | None = None,
) -> ReconciliationIssue:
    issue, _created = _upsert_issue(
        session,
        now=datetime.now(UTC).replace(tzinfo=None),
        issue_type=issue_type,
        symbol=symbol,
        severity=severity,
        reason=reason,
        remote_order_id=remote_order_id,
        local_order_id=local_order_id,
        position_id=position_id,
        trade_plan_id=trade_plan_id,
        payload=payload,
    )
    return issue


def resolve_stale_issues(
    session: Session,
    currently_seen_issue_keys: set[IssueKey],
    *,
    now: datetime | None = None,
) -> int:
    resolved = 0
    resolved_at = now or datetime.now(UTC).replace(tzinfo=None)
    open_issues = list(
        session.scalars(
            select(ReconciliationIssue).where(
                ReconciliationIssue.status == "OPEN",
                ReconciliationIssue.issue_type.in_(MANAGED_ISSUE_TYPES),
            )
        )
    )
    for issue in open_issues:
        if _issue_key(issue) in currently_seen_issue_keys:
            continue
        issue.status = "RESOLVED"
        issue.resolved_at = resolved_at
        issue.last_seen_at = resolved_at
        resolved += 1
    return resolved


def _check_remote_positions_without_local(
    session: Session,
    now: datetime,
    seen: set[IssueKey],
    remote_positions_by_symbol: dict[str, dict],
) -> int:
    opened = 0
    for symbol, row in remote_positions_by_symbol.items():
        if _local_open_position(session, symbol):
            continue
        issue, created = _upsert_issue(
            session,
            now=now,
            issue_type="REMOTE_POSITION_WITHOUT_LOCAL",
            symbol=symbol,
            severity="HIGH",
            reason="富途账户存在持仓，但本地没有 OPEN Position",
            payload={
                "remote_qty": _int_value(row.get("qty") or row.get("quantity")),
                "cost_price": _float_value(row.get("cost_price") or row.get("average_price")),
                "market_value": _float_value(row.get("market_val") or row.get("market_value")),
                "pl_ratio": _float_value(row.get("pl_ratio")),
            },
        )
        seen.add(_issue_key(issue))
        opened += int(created)
    return opened


def _check_local_positions(
    session: Session,
    now: datetime,
    seen: set[IssueKey],
    remote_positions_by_symbol: dict[str, dict],
) -> int:
    opened = 0
    positions = list(
        session.scalars(
            select(Position).where(
                Position.status == "OPEN",
                Position.source.in_({"FUTU_DETECTED", "LOCAL_AND_FUTU_CONFIRMED", "LOCAL_STRATEGY"}),
            )
        )
    )
    for position in positions:
        symbol = normalize_symbol(position.symbol)
        remote = remote_positions_by_symbol.get(symbol)
        if not remote:
            issue, created = _upsert_issue(
                session,
                now=now,
                issue_type="LOCAL_POSITION_MISSING_REMOTE",
                symbol=symbol,
                severity="HIGH",
                position_id=position.id,
                trade_plan_id=position.source_trade_plan_id,
                reason="本地仍为 OPEN，但富途账户已无该持仓",
                payload={"local_shares": position.shares, "source": position.source},
            )
            seen.add(_issue_key(issue))
            opened += int(created)
            continue
        remote_qty = _int_value(remote.get("qty") or remote.get("quantity"))
        if position.shares != remote_qty:
            issue, created = _upsert_issue(
                session,
                now=now,
                issue_type="POSITION_QTY_MISMATCH",
                symbol=symbol,
                severity="HIGH",
                position_id=position.id,
                trade_plan_id=position.source_trade_plan_id,
                reason="本地持仓数量与富途持仓数量不一致",
                payload={
                    "local_shares": position.shares,
                    "remote_qty": remote_qty,
                    "available_shares": position.available_shares,
                },
            )
            seen.add(_issue_key(issue))
            opened += int(created)
        remote_cost = _float_value(remote.get("cost_price") or remote.get("average_price"))
        if remote_cost > 0 and position.entry_price > 0:
            diff_pct = abs(position.entry_price - remote_cost) / remote_cost
            if diff_pct > 0.01:
                issue, created = _upsert_issue(
                    session,
                    now=now,
                    issue_type="POSITION_COST_MISMATCH",
                    symbol=symbol,
                    severity="WARN",
                    position_id=position.id,
                    trade_plan_id=position.source_trade_plan_id,
                    reason="本地持仓成本与富途持仓成本偏差超过 1%",
                    payload={
                        "local_entry_price": position.entry_price,
                        "remote_cost_price": remote_cost,
                        "diff_pct": round(diff_pct, 6),
                    },
                )
                seen.add(_issue_key(issue))
                opened += int(created)
    return opened


def _check_remote_orders_without_local(session: Session, now: datetime, seen: set[IssueKey], remote_orders: list[dict]) -> int:
    opened = 0
    for row in remote_orders:
        order_id = str(row.get("order_id") or "")
        if not order_id:
            continue
        local = session.scalar(select(SimOrder).where(SimOrder.futu_order_id == order_id).limit(1))
        if local:
            continue
        symbol = normalize_symbol(row.get("code") or row.get("symbol"))
        issue, created = _upsert_issue(
            session,
            now=now,
            issue_type="REMOTE_ORDER_WITHOUT_LOCAL",
            symbol=symbol,
            severity="WARN",
            remote_order_id=order_id,
            reason="富途 open orders 存在订单，但本地没有对应 SimOrder",
            payload=row,
        )
        seen.add(_issue_key(issue))
        opened += int(created)
    return opened


def _check_local_orders(
    session: Session,
    now: datetime,
    seen: set[IssueKey],
    remote_order_ids: set[str],
    remote_deal_order_ids: set[str],
) -> int:
    opened = 0
    orders = list(session.scalars(select(SimOrder).where(SimOrder.status.in_(RECONCILE_ORDER_STATUSES))))
    for order in orders:
        futu_order_id = order.futu_order_id or ""
        if futu_order_id and (futu_order_id in remote_order_ids or futu_order_id in remote_deal_order_ids):
            continue
        issue_type = "SELL_ORDER_STUCK" if order.side == "SELL" else "LOCAL_ORDER_MISSING_REMOTE"
        severity = "HIGH" if order.side == "SELL" else "WARN"
        issue, created = _upsert_issue(
            session,
            now=now,
            issue_type=issue_type,
            symbol=normalize_symbol(order.symbol),
            severity=severity,
            remote_order_id=futu_order_id,
            local_order_id=order.id,
            trade_plan_id=order.trade_plan_id,
            reason=(
                "风控卖出单未在远端 open orders 或成交中确认"
                if order.side == "SELL"
                else "本地订单未在远端 open orders 或成交中确认"
            ),
            payload={
                "side": order.side,
                "status": order.status,
                "qty": order.qty,
                "limit_price": order.limit_price,
                "submitted_at": order.submitted_at.isoformat() if order.submitted_at else "",
                "reason": order.reason,
            },
        )
        seen.add(_issue_key(issue))
        opened += int(created)
    return opened


def _check_closed_unverified(session: Session, now: datetime, seen: set[IssueKey]) -> int:
    opened = 0
    positions = list(session.scalars(select(Position).where(Position.status == "CLOSED_UNVERIFIED")))
    for position in positions:
        issue, created = _upsert_issue(
            session,
            now=now,
            issue_type="CLOSE_UNVERIFIED",
            symbol=normalize_symbol(position.symbol),
            severity="WARN",
            position_id=position.id,
            trade_plan_id=position.source_trade_plan_id,
            reason="仓位已从富途消失，但本地没有确认 SELL 成交",
            payload={
                "shares": position.shares,
                "entry_price": position.entry_price,
                "exit_reason": position.exit_reason,
                "close_source": position.close_source,
            },
        )
        seen.add(_issue_key(issue))
        opened += int(created)
    return opened


def _check_inferred_buy_orders(session: Session, now: datetime, seen: set[IssueKey]) -> int:
    opened = 0
    orders = list(session.scalars(select(SimOrder).where(SimOrder.status == "FILLED_INFERRED", SimOrder.side == "BUY")))
    for order in orders:
        issue, created = _upsert_issue(
            session,
            now=now,
            issue_type="BUY_ORDER_INFERRED_FILLED",
            symbol=normalize_symbol(order.symbol),
            severity="INFO",
            remote_order_id=order.futu_order_id or "",
            local_order_id=order.id,
            trade_plan_id=order.trade_plan_id,
            reason="BUY 订单由远端持仓反推为成交",
            payload={"qty": order.qty, "dealt_qty": order.dealt_qty, "dealt_avg_price": order.dealt_avg_price},
        )
        seen.add(_issue_key(issue))
        opened += int(created)
    return opened


def _upsert_issue(
    session: Session,
    *,
    now: datetime,
    issue_type: str,
    symbol: str = "",
    severity: str = "WARN",
    reason: str = "",
    remote_order_id: str = "",
    local_order_id: int | None = None,
    position_id: int | None = None,
    trade_plan_id: int | None = None,
    payload: dict | None = None,
) -> tuple[ReconciliationIssue, bool]:
    normalized_symbol = normalize_symbol(symbol) if symbol else ""
    issue = session.scalar(
        select(ReconciliationIssue)
        .where(
            ReconciliationIssue.status == "OPEN",
            ReconciliationIssue.issue_type == issue_type,
            ReconciliationIssue.symbol == normalized_symbol,
            ReconciliationIssue.remote_order_id == (remote_order_id or ""),
            _nullable_equals(ReconciliationIssue.local_order_id, local_order_id),
            _nullable_equals(ReconciliationIssue.position_id, position_id),
            _nullable_equals(ReconciliationIssue.trade_plan_id, trade_plan_id),
        )
        .limit(1)
    )
    created = issue is None
    if issue is None:
        issue = ReconciliationIssue(
            issue_type=issue_type,
            symbol=normalized_symbol,
            remote_order_id=remote_order_id or "",
            local_order_id=local_order_id,
            position_id=position_id,
            trade_plan_id=trade_plan_id,
            first_seen_at=now,
        )
        session.add(issue)
    issue.severity = severity
    issue.reason = reason
    issue.payload_json = json.dumps(payload or {}, ensure_ascii=False, default=str)
    issue.last_seen_at = now
    issue.resolved_at = None
    return issue, created


def _health_payload(
    session: Session,
    issues_opened: int,
    issues_resolved: int,
    *,
    deals_supported: bool,
    reason: str = "",
) -> dict[str, object]:
    open_issues = list(session.scalars(select(ReconciliationIssue).where(ReconciliationIssue.status == "OPEN")))
    severity = _max_severity(issue.severity for issue in open_issues)
    critical_issues = sum(issue.severity == "CRITICAL" for issue in open_issues)
    high_issues = sum(issue.severity == "HIGH" for issue in open_issues)
    allow_new_entries = not any(issue.severity in BLOCKING_SEVERITIES for issue in open_issues)
    reason_text = reason or _health_reason(severity)
    return {
        "ok": allow_new_entries,
        "severity": severity,
        "mode": _gate_mode(allow_new_entries, severity, reason_text),
        "issues_opened": issues_opened,
        "issues_resolved": issues_resolved,
        "open_issues": len(open_issues),
        "critical_issues": critical_issues,
        "high_issues": high_issues,
        "allow_new_entries": allow_new_entries,
        "reason": reason_text,
        "deals_supported": deals_supported,
    }


def _health_reason(severity: str) -> str:
    if severity == "CRITICAL":
        return "存在关键账户同步或对账问题"
    if severity == "HIGH":
        return "存在高优先级交易账本不一致"
    if severity == "WARN":
        return "存在非阻断对账提醒"
    return "交易账本对账正常"


def _gate_mode(allow_new_entries: bool, severity: str, reason: str = "") -> str:
    if severity == "CRITICAL" and ("同步失败" in reason or "账户" in reason):
        return "SYNC_FAILED"
    if not allow_new_entries or severity in {"HIGH", "CRITICAL"}:
        return "PROTECTIVE"
    if severity == "WARN":
        return "DEGRADED"
    return "NORMAL"


def _normalize_gate_payload(payload: dict) -> dict[str, object]:
    severity = str(payload.get("severity") or "INFO")
    allow_new_entries = bool(payload.get("allow_new_entries"))
    reason = str(payload.get("reason") or "")
    return {
        "allow_new_entries": allow_new_entries,
        "severity": severity,
        "mode": str(payload.get("mode") or _gate_mode(allow_new_entries, severity, reason)),
        "reason": reason,
        "open_issues": int(payload.get("open_issues") or 0),
        "high_issues": int(payload.get("high_issues") or 0),
        "critical_issues": int(payload.get("critical_issues") or 0),
        "updated_at": payload.get("updated_at"),
    }


def _max_severity(values) -> str:
    result = "INFO"
    for value in values:
        if SEVERITY_RANK.get(value, 0) > SEVERITY_RANK[result]:
            result = value
    return result


def _remote_positions_by_symbol(rows: list[dict]) -> dict[str, dict]:
    positions: dict[str, dict] = {}
    for row in rows:
        qty = _int_value(row.get("qty") or row.get("quantity"))
        if qty <= 0:
            continue
        symbol = normalize_symbol(row.get("code") or row.get("symbol"))
        if symbol:
            positions[symbol] = row
    return positions


def _local_open_position(session: Session, symbol: str) -> Position | None:
    normalized = normalize_symbol(symbol)
    aliases = {normalized, normalized.removeprefix("US.")}
    return session.scalar(select(Position).where(Position.status == "OPEN", Position.symbol.in_(aliases)).limit(1))


def _issue_key(issue: ReconciliationIssue) -> IssueKey:
    return IssueKey(
        issue.issue_type,
        issue.symbol or "",
        issue.remote_order_id or "",
        issue.local_order_id,
        issue.position_id,
        issue.trade_plan_id,
    )


def _float_value(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _int_value(value: Any) -> int:
    return int(_float_value(value))


def _nullable_equals(column, value):
    return column.is_(None) if value is None else column == value
