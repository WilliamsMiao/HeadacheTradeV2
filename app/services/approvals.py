from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ApprovalRecord, MarketState, Position, TradeSignal, TradingState
from app.services.corrections import reconcile_pending_entry
from app.services.risk import get_or_create_risk_config


def approve_signal(session: Session, signal_id: int, note: str = "") -> TradeSignal:
    signal = session.get(TradeSignal, signal_id)
    if signal is None:
        raise ValueError(f"signal {signal_id} not found")
    if signal.status != "PENDING":
        raise ValueError(f"signal {signal_id} is not pending")
    if signal.signal_type == "ENTRY":
        if signal.stop_price is None or signal.entry_price is None or not signal.shares:
            raise ValueError("entry signal missing stop, entry, or shares")
        if (
            signal.source_structure_id is None
            or signal.trigger_timeframe != "15m"
            or signal.trigger_ts is None
            or signal.trigger_level is None
        ):
            raise ValueError("entry signal missing structure or trigger source")
        market = session.scalar(select(MarketState).order_by(MarketState.updated_at.desc()).limit(1))
        correction = reconcile_pending_entry(session, signal.symbol, market.state if market else "RISK_ON")
        if correction:
            session.commit()
            raise ValueError(f"entry signal is no longer valid: {correction.reason}")
        position = Position(
            symbol=signal.symbol,
            entry_signal_id=signal.id,
            entry_price=signal.entry_price,
            stop_price=signal.stop_price,
            shares=signal.shares,
            risk_amount=signal.risk_amount or 0,
        )
        session.add(position)
        _set_state(session, signal.symbol, "IN_POSITION", "manual approval created simulated position")
    elif signal.signal_type == "REDUCE":
        position = session.scalar(select(Position).where(Position.symbol == signal.symbol, Position.status == "OPEN"))
        if position and signal.shares:
            position.shares = max(0, position.shares - signal.shares)
            if position.shares == 0:
                position.status = "CLOSED"
                position.exit_reason = "fully reduced by approval"
                _cooldown(session, signal.symbol)
            else:
                _set_state(session, signal.symbol, "IN_POSITION", "manual approval reduced simulated position")
    elif signal.signal_type == "EXIT":
        position = session.scalar(select(Position).where(Position.symbol == signal.symbol, Position.status == "OPEN"))
        if position:
            position.status = "CLOSED"
            position.exit_reason = signal.reason
            _cooldown(session, signal.symbol)
    signal.status = "APPROVED"
    session.add(ApprovalRecord(signal_id=signal.id, decision="APPROVED", note=note))
    session.commit()
    return signal


def reject_signal(session: Session, signal_id: int, note: str = "") -> TradeSignal:
    signal = session.get(TradeSignal, signal_id)
    if signal is None:
        raise ValueError(f"signal {signal_id} not found")
    signal.status = "REJECTED"
    session.add(ApprovalRecord(signal_id=signal.id, decision="REJECTED", note=note))
    session.commit()
    return signal


def _set_state(session: Session, symbol: str, state: str, reason: str) -> None:
    record = session.scalar(select(TradingState).where(TradingState.symbol == symbol))
    if record:
        record.state = state
        record.last_reason = reason


def _cooldown(session: Session, symbol: str) -> None:
    config = get_or_create_risk_config(session)
    record = session.scalar(select(TradingState).where(TradingState.symbol == symbol))
    if record:
        record.state = "COOLDOWN"
        record.cooldown_until = date.today() + timedelta(days=config.cooldown_days)
        record.last_reason = "simulated exit approved, cooldown started"
