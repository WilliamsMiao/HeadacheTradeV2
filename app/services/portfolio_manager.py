from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Position, SimOrder, TradePlan


@dataclass(frozen=True)
class PortfolioState:
    status: str
    available_cash: float
    open_positions: int
    open_orders: int
    reason: str


def get_portfolio_state(session: Session, trade_provider, settings: Settings) -> PortfolioState:
    account = trade_provider.get_account_info() if trade_provider else {}
    available_cash = float(account.get("cash") or account.get("power") or 0)
    positions = list(session.scalars(select(Position).where(Position.status == "OPEN")))
    orders = list(session.scalars(select(SimOrder).where(SimOrder.status.in_({"SUBMITTED", "PARTIALLY_FILLED"}))))
    if len(positions) >= settings.max_positions:
        status, reason = "CAPITAL_FULL", "已达到最大持仓数"
    elif available_cash <= 0 and trade_provider:
        status, reason = "CAPITAL_LIMITED", "模拟账户可用资金不足"
    else:
        status, reason = "CAPITAL_AVAILABLE", "资金允许评估新计划"
    return PortfolioState(status, available_cash, len(positions), len(orders), reason)


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
