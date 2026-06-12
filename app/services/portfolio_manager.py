import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Position, SimOrder, SystemConfig, TradePlan


@dataclass(frozen=True)
class PortfolioState:
    status: str
    available_cash: float
    open_positions: int
    open_orders: int
    reason: str


def get_portfolio_state(session: Session, trade_provider, settings: Settings) -> PortfolioState:
    try:
        account = trade_provider.get_account_info() if trade_provider else {}
        remote_positions = trade_provider.get_positions() if trade_provider else []
        remote_orders = trade_provider.get_open_orders() if trade_provider else []
        remote_position_count = sum(_position_is_open(row) for row in remote_positions)
        remote_order_count = sum(_order_is_open(row) for row in remote_orders)
        available_cash = float(account.get("cash") or account.get("power") or 0)
        positions = list(session.scalars(select(Position).where(Position.status == "OPEN")))
        orders = list(session.scalars(select(SimOrder).where(SimOrder.status.in_({"SUBMITTED", "PARTIALLY_FILLED"}))))
        open_positions = max(len(positions), remote_position_count)
        open_orders = max(len(orders), remote_order_count)
        if open_positions >= settings.max_positions:
            status, reason = "CAPITAL_FULL", "已达到最大持仓数"
        elif available_cash <= 0 and trade_provider:
            status, reason = "CAPITAL_LIMITED", "模拟账户可用资金不足"
        else:
            status, reason = "CAPITAL_AVAILABLE", "资金允许评估新计划"
        state = PortfolioState(status, available_cash, open_positions, open_orders, reason)
        _save_portfolio_sync(
            session,
            ok=True,
            state=state,
            remote_positions=remote_position_count,
            remote_orders=remote_order_count,
        )
        _apply_portfolio_state_to_plans(session, state, settings)
        return state
    except Exception as exc:
        state = PortfolioState(
            "CAPITAL_UNKNOWN",
            0,
            0,
            0,
            f"无法确认模拟账户资金、持仓或未成交订单：{exc}",
        )
        _save_portfolio_sync(session, ok=False, state=state, error=str(exc))
        _apply_portfolio_state_to_plans(session, state, settings)
        return state


def capital_allows_new_order(
    session: Session,
    plan: TradePlan,
    state: PortfolioState,
    settings: Settings,
) -> tuple[bool, str]:
    if state.status != "CAPITAL_AVAILABLE":
        return False, state.reason
    if session.scalar(select(Position).where(Position.symbol == plan.symbol, Position.status == "OPEN")):
        return False, "同标的已有模拟持仓"
    if session.scalar(
        select(SimOrder).where(
            SimOrder.symbol == plan.symbol,
            SimOrder.status.in_({"SUBMITTED", "PARTIALLY_FILLED"}),
        )
    ):
        return False, "同标的已有未完成模拟订单"
    if state.open_positions >= settings.max_positions:
        return False, "已达到最大持仓数"
    return True, "资金闸门通过"


def rank_waitlisted_plans(session: Session) -> list[TradePlan]:
    plans = list(
        session.scalars(
            select(TradePlan)
            .where(TradePlan.status.in_({"WAITLIST", "MISSED_BY_CAPITAL"}))
            .order_by(TradePlan.last_validated_at.asc(), TradePlan.id.asc())
        )
    )
    plans.sort(key=lambda plan: (0 if plan.priority_level == "S" else 1, plan.last_validated_at, plan.id))
    for index, plan in enumerate(plans, start=1):
        plan.waitlist_rank = index
    session.commit()
    return plans


def portfolio_sync_status(session: Session) -> dict:
    record = session.scalar(select(SystemConfig).where(SystemConfig.key == "portfolio_sync_status"))
    if not record:
        return {"ok": False, "status": "CAPITAL_UNKNOWN", "error": "尚未同步 Futu 模拟账户", "updated_at": None}
    try:
        return json.loads(record.value)
    except json.JSONDecodeError:
        return {"ok": False, "status": "CAPITAL_UNKNOWN", "error": "组合账户同步状态损坏", "updated_at": None}


def check_sim_account_connection(session: Session, trade_provider, settings: Settings) -> dict:
    state = get_portfolio_state(session, trade_provider, settings)
    saved = portfolio_sync_status(session)
    return {
        "ok": bool(saved.get("ok")),
        "status": state.status,
        "account_connected": bool(saved.get("ok")),
        "positions_connected": bool(saved.get("ok")),
        "open_orders_connected": bool(saved.get("ok")),
        "remote_positions": saved.get("remote_positions", 0),
        "remote_orders": saved.get("remote_orders", 0),
        "updated_at": saved.get("updated_at"),
        "error": saved.get("error", ""),
    }


def _save_portfolio_sync(
    session: Session,
    *,
    ok: bool,
    state: PortfolioState,
    remote_positions: int = 0,
    remote_orders: int = 0,
    error: str = "",
) -> None:
    record = session.scalar(select(SystemConfig).where(SystemConfig.key == "portfolio_sync_status"))
    if record is None:
        record = SystemConfig(key="portfolio_sync_status")
        session.add(record)
    record.value = json.dumps({
        "ok": ok,
        "status": state.status,
        "available_cash": state.available_cash,
        "open_positions": state.open_positions,
        "open_orders": state.open_orders,
        "remote_positions": remote_positions,
        "remote_orders": remote_orders,
        "reason": state.reason,
        "error": error,
        "updated_at": datetime.now(UTC).isoformat(),
    }, ensure_ascii=False)
    session.commit()


def _apply_portfolio_state_to_plans(session: Session, state: PortfolioState, settings: Settings) -> None:
    plans = session.scalars(
        select(TradePlan).where(
            TradePlan.priority_level.in_({"S", "A"}),
            TradePlan.status.in_({
                "ACTIVE", "PLANNED", "ARMED", "TRIGGERED", "WAITLIST",
                "MISSED_BY_CAPITAL", "NO_CHASE", "WAIT_PULLBACK",
            }),
        )
    )
    for plan in plans:
        plan.capital_status = state.status
        plan.capital_reason = "" if state.status == "CAPITAL_AVAILABLE" else state.reason
        plan.available_cash_snapshot = state.available_cash
        plan.max_new_position_value = state.available_cash * settings.max_symbol_position_pct if state.available_cash > 0 else 0
    session.commit()


def _position_is_open(row: dict) -> bool:
    try:
        return float(row.get("qty") or row.get("quantity") or 0) > 0
    except (TypeError, ValueError):
        return False


def _order_is_open(row: dict) -> bool:
    status = str(row.get("order_status") or row.get("status") or "").upper()
    return status in {"SUBMITTED", "SUBMITTING", "WAITING_SUBMIT", "PARTIALLY_FILLED", "PART_FILLED"}
