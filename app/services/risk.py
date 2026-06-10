from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import RiskResult, STRUCTURE_TIMEFRAME
from app.models import Indicator, Position, RiskConfig, StructureEvent, WatchlistItem


@dataclass(frozen=True)
class StructureStop:
    stop_price: float
    atr: float
    reference_level: float
    reason: str


def calculate_structure_stop(
    session: Session,
    structure: StructureEvent,
    entry_price: float,
    script: str,
) -> StructureStop | None:
    if structure.id is None or structure.timeframe != STRUCTURE_TIMEFRAME or entry_price <= 0:
        return None
    indicator = session.scalar(
        select(Indicator)
        .where(
            Indicator.symbol == structure.symbol,
            Indicator.timeframe == STRUCTURE_TIMEFRAME,
            Indicator.ts == structure.event_ts,
        )
        .limit(1)
    )
    if indicator is None or indicator.atr is None or indicator.atr <= 0:
        return None

    if script == "SCRIPT_A_BOTTOM_TREND_RESUME":
        if structure.event_type != "BOTTOM_STRUCTURE" or structure.pivot_low is None:
            return None
        reference_level = structure.pivot_low
        stop_price = reference_level - indicator.atr * 0.5
        reason = (
            f"60m bottom structure pivot {reference_level:.2f} minus "
            f"0.5 ATR ({indicator.atr:.2f})"
        )
    elif script == "SCRIPT_B_TOP_INVALIDATION_CONTINUATION":
        if structure.event_type != "TOP_INVALIDATED" or structure.invalidation_level is None:
            return None
        reference_level = structure.invalidation_level
        stop_price = reference_level - indicator.atr * 0.25
        reason = (
            f"60m top invalidation breakout {reference_level:.2f} minus "
            f"0.25 ATR ({indicator.atr:.2f})"
        )
    else:
        return None

    if stop_price <= 0 or stop_price >= entry_price:
        return None
    return StructureStop(
        stop_price=stop_price,
        atr=indicator.atr,
        reference_level=reference_level,
        reason=reason,
    )


def get_or_create_risk_config(session: Session) -> RiskConfig:
    config = session.scalar(select(RiskConfig).order_by(RiskConfig.id.asc()).limit(1))
    if config is None:
        config = RiskConfig()
        session.add(config)
        session.commit()
        session.refresh(config)
    return config


def calculate_position_size(
    config: RiskConfig,
    entry_price: float,
    stop_price: float | None,
    market_state: str,
    script: str,
) -> RiskResult | None:
    if stop_price is None or entry_price <= 0 or stop_price <= 0 or stop_price >= entry_price:
        return None
    risk_per_share = entry_price - stop_price
    multiplier = 1.0
    if market_state == "NEUTRAL_POSITIVE":
        multiplier *= config.neutral_risk_multiplier
    if script == "SCRIPT_B_TOP_INVALIDATION_CONTINUATION":
        multiplier *= config.script_b_risk_multiplier
    allowed_loss = config.account_equity * config.risk_per_trade_pct * multiplier
    shares_by_risk = int(allowed_loss // risk_per_share)
    max_value = config.account_equity * config.max_symbol_position_pct
    shares_by_cap = int(max_value // entry_price)
    shares = max(0, min(shares_by_risk, shares_by_cap))
    if shares <= 0:
        return None
    position_value = shares * entry_price
    return RiskResult(
        entry_price=entry_price,
        stop_price=stop_price,
        risk_per_share=risk_per_share,
        allowed_loss=allowed_loss,
        shares=shares,
        position_value=position_value,
        position_pct=position_value / config.account_equity,
    )


def portfolio_allows_new_position(session: Session, symbol: str, config: RiskConfig) -> tuple[bool, str]:
    open_positions = list(session.scalars(select(Position).where(Position.status == "OPEN")))
    if any(position.symbol == symbol for position in open_positions):
        return False, f"{symbol} already has open simulated position"
    if len(open_positions) >= config.max_positions:
        return False, "maximum open positions reached"
    item = session.scalar(select(WatchlistItem).where(WatchlistItem.symbol == symbol))
    if item and item.industry:
        same_industry_value = 0.0
        for position in open_positions:
            other = session.scalar(select(WatchlistItem).where(WatchlistItem.symbol == position.symbol))
            if other and other.industry == item.industry:
                same_industry_value += position.shares * position.entry_price
        if same_industry_value / config.account_equity >= config.max_industry_exposure_pct:
            return False, f"industry exposure limit reached for {item.industry}"
    return True, "portfolio risk checks passed"
