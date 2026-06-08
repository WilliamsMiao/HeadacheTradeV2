from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class WatchlistItem(Base, TimestampMixin):
    __tablename__ = "watchlist_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    industry: Mapped[str] = mapped_column(String(128), default="")
    source_group: Mapped[str] = mapped_column(String(128), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class KLine(Base, TimestampMixin):
    __tablename__ = "klines"
    __table_args__ = (UniqueConstraint("symbol", "timeframe", "ts", name="uq_kline_symbol_timeframe_ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(16), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float, default=0)
    data_ok: Mapped[bool] = mapped_column(Boolean, default=True)
    anomaly_reason: Mapped[str] = mapped_column(Text, default="")


class Indicator(Base, TimestampMixin):
    __tablename__ = "indicators"
    __table_args__ = (UniqueConstraint("symbol", "timeframe", "ts", name="uq_indicator_symbol_timeframe_ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(16), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)
    ma20: Mapped[float | None] = mapped_column(Float, nullable=True)
    ma60: Mapped[float | None] = mapped_column(Float, nullable=True)
    macd_dif: Mapped[float | None] = mapped_column(Float, nullable=True)
    macd_dea: Mapped[float | None] = mapped_column(Float, nullable=True)
    macd_hist: Mapped[float | None] = mapped_column(Float, nullable=True)
    atr: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume_ma20: Mapped[float | None] = mapped_column(Float, nullable=True)


class MarketState(Base, TimestampMixin):
    __tablename__ = "market_states"
    __table_args__ = (UniqueConstraint("as_of", name="uq_market_state_as_of"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    as_of: Mapped[date] = mapped_column(Date, index=True)
    state: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(Text)


class StockTrend(Base, TimestampMixin):
    __tablename__ = "stock_trends"
    __table_args__ = (UniqueConstraint("symbol", "as_of", name="uq_stock_trend_symbol_as_of"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    as_of: Mapped[date] = mapped_column(Date, index=True)
    trend: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(Text)


class StructureEvent(Base, TimestampMixin):
    __tablename__ = "structure_events"
    __table_args__ = (UniqueConstraint("symbol", "timeframe", "event_type", "event_ts", name="uq_structure_event"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(16), index=True)
    event_type: Mapped[str] = mapped_column(String(48), index=True)
    event_ts: Mapped[datetime] = mapped_column(DateTime, index=True)
    price: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)
    invalidated: Mapped[bool] = mapped_column(Boolean, default=False)
    follow_5_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    follow_10_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    follow_20_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_up_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_down_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    triggered_entry: Mapped[bool] = mapped_column(Boolean, default=False)
    became_failed: Mapped[bool] = mapped_column(Boolean, default=False)
    market_state: Mapped[str] = mapped_column(String(32), default="")
    stock_trend: Mapped[str] = mapped_column(String(32), default="")


class TradingState(Base, TimestampMixin):
    __tablename__ = "trading_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    state: Mapped[str] = mapped_column(String(48), default="IDLE", index=True)
    next_wait: Mapped[str] = mapped_column(Text, default="")
    cooldown_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_reason: Mapped[str] = mapped_column(Text, default="")


class StateTransitionLog(Base, TimestampMixin):
    __tablename__ = "state_transition_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    from_state: Mapped[str] = mapped_column(String(48))
    to_state: Mapped[str] = mapped_column(String(48))
    reason: Mapped[str] = mapped_column(Text)


class RiskConfig(Base, TimestampMixin):
    __tablename__ = "risk_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_equity: Mapped[float] = mapped_column(Float, default=100000)
    risk_per_trade_pct: Mapped[float] = mapped_column(Float, default=0.01)
    neutral_risk_multiplier: Mapped[float] = mapped_column(Float, default=0.5)
    script_b_risk_multiplier: Mapped[float] = mapped_column(Float, default=0.5)
    max_positions: Mapped[int] = mapped_column(Integer, default=5)
    max_symbol_position_pct: Mapped[float] = mapped_column(Float, default=0.2)
    max_industry_exposure_pct: Mapped[float] = mapped_column(Float, default=0.35)
    cooldown_days: Mapped[int] = mapped_column(Integer, default=10)


class TradeSignal(Base, TimestampMixin):
    __tablename__ = "trade_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    signal_type: Mapped[str] = mapped_column(String(48), index=True)
    script: Mapped[str] = mapped_column(String(48), default="")
    status: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    action: Mapped[str] = mapped_column(String(48), default="")
    entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_position_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    shares: Mapped[int | None] = mapped_column(Integer, nullable=True)
    risk_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_r: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str] = mapped_column(Text)
    score_display: Mapped[float | None] = mapped_column(Float, nullable=True)


class ApprovalRecord(Base, TimestampMixin):
    __tablename__ = "approval_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_id: Mapped[int] = mapped_column(Integer, index=True)
    decision: Mapped[str] = mapped_column(String(32))
    note: Mapped[str] = mapped_column(Text, default="")


class Position(Base, TimestampMixin):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="OPEN", index=True)
    entry_signal_id: Mapped[int] = mapped_column(Integer, index=True)
    entry_price: Mapped[float] = mapped_column(Float)
    stop_price: Mapped[float] = mapped_column(Float)
    trailing_stop: Mapped[float | None] = mapped_column(Float, nullable=True)
    shares: Mapped[int] = mapped_column(Integer)
    risk_amount: Mapped[float] = mapped_column(Float)
    current_r: Mapped[float] = mapped_column(Float, default=0)
    exit_reason: Mapped[str] = mapped_column(Text, default="")


class ReviewStat(Base, TimestampMixin):
    __tablename__ = "review_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_type: Mapped[str] = mapped_column(String(32), index=True)
    subject_id: Mapped[int] = mapped_column(Integer, index=True)
    metric: Mapped[str] = mapped_column(String(64), index=True)
    value: Mapped[float] = mapped_column(Float)


class SystemConfig(Base, TimestampMixin):
    __tablename__ = "system_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    value: Mapped[str] = mapped_column(Text, default="")
