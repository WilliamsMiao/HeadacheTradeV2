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
    turnover: Mapped[float] = mapped_column(Float, default=0)
    data_ok: Mapped[bool] = mapped_column(Boolean, default=True)
    anomaly_reason: Mapped[str] = mapped_column(Text, default="")


class Indicator(Base, TimestampMixin):
    __tablename__ = "indicators"
    __table_args__ = (UniqueConstraint("symbol", "timeframe", "ts", name="uq_indicator_symbol_timeframe_ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(16), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)
    ma5: Mapped[float | None] = mapped_column(Float, nullable=True)
    ma10: Mapped[float | None] = mapped_column(Float, nullable=True)
    ma20: Mapped[float | None] = mapped_column(Float, nullable=True)
    ma60: Mapped[float | None] = mapped_column(Float, nullable=True)
    ema5: Mapped[float | None] = mapped_column(Float, nullable=True)
    ema10: Mapped[float | None] = mapped_column(Float, nullable=True)
    ema20: Mapped[float | None] = mapped_column(Float, nullable=True)
    ema60: Mapped[float | None] = mapped_column(Float, nullable=True)
    macd_dif: Mapped[float | None] = mapped_column(Float, nullable=True)
    macd_dea: Mapped[float | None] = mapped_column(Float, nullable=True)
    macd_hist: Mapped[float | None] = mapped_column(Float, nullable=True)
    atr: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume_ma20: Mapped[float | None] = mapped_column(Float, nullable=True)
    boll_mid: Mapped[float | None] = mapped_column(Float, nullable=True)
    boll_upper: Mapped[float | None] = mapped_column(Float, nullable=True)
    boll_lower: Mapped[float | None] = mapped_column(Float, nullable=True)
    rsi6: Mapped[float | None] = mapped_column(Float, nullable=True)
    rsi14: Mapped[float | None] = mapped_column(Float, nullable=True)
    kdj_k: Mapped[float | None] = mapped_column(Float, nullable=True)
    kdj_d: Mapped[float | None] = mapped_column(Float, nullable=True)
    kdj_j: Mapped[float | None] = mapped_column(Float, nullable=True)
    turnover: Mapped[float | None] = mapped_column(Float, nullable=True)
    turnover_ma20: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    amplitude_pct: Mapped[float | None] = mapped_column(Float, nullable=True)


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


class DailyState(Base, TimestampMixin):
    __tablename__ = "daily_states"
    __table_args__ = (UniqueConstraint("symbol", "as_of", name="uq_daily_state_symbol_as_of"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    as_of: Mapped[date] = mapped_column(Date, index=True)
    state: Mapped[str] = mapped_column(String(32), index=True)
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
    pivot_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    pivot_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    confirm_level: Mapped[float | None] = mapped_column(Float, nullable=True)
    invalidation_level: Mapped[float | None] = mapped_column(Float, nullable=True)
    trigger_level: Mapped[float | None] = mapped_column(Float, nullable=True)
    parent_event_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    script_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
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
    direction: Mapped[str] = mapped_column(String(16), default="")
    stage: Mapped[str] = mapped_column(String(24), default="")
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    battle_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    suggested_action: Mapped[str] = mapped_column(String(64), default="")


class CandidateStock(Base, TimestampMixin):
    __tablename__ = "candidate_stocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    market: Mapped[str] = mapped_column(String(16), default="US")
    pool_type: Mapped[str] = mapped_column(String(32), index=True)
    pool_types_json: Mapped[str] = mapped_column(Text, default="[]")
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    selected_reason: Mapped[str] = mapped_column(Text, default="")
    rank_score: Mapped[float] = mapped_column(Float, default=0, index=True)
    liquidity_score: Mapped[float] = mapped_column(Float, default=0)
    heat_score: Mapped[float] = mapped_column(Float, default=0)
    technical_score: Mapped[float] = mapped_column(Float, default=0)
    raw_metrics_json: Mapped[str] = mapped_column(Text, default="{}")
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    selected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    first_selected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_selected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    candidate_age_days: Mapped[int] = mapped_column(Integer, default=0)
    candidate_status: Mapped[str] = mapped_column(String(24), default="ACTIVE_TODAY", index=True)
    carry_reason: Mapped[str] = mapped_column(Text, default="")
    dropped_reason: Mapped[str] = mapped_column(Text, default="")
    risk_flags_json: Mapped[str] = mapped_column(Text, default="[]")


class CandidateSnapshot(Base, TimestampMixin):
    __tablename__ = "candidate_snapshots"
    __table_args__ = (UniqueConstraint("run_id", "symbol", name="uq_candidate_snapshot_run_symbol"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    pool_type: Mapped[str] = mapped_column(String(32), index=True)
    pool_types_json: Mapped[str] = mapped_column(Text, default="[]")
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    rank_score: Mapped[float] = mapped_column(Float, default=0)
    raw_metrics_json: Mapped[str] = mapped_column(Text, default="{}")


class BattlePoolItem(Base, TimestampMixin):
    __tablename__ = "battle_pool_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    direction: Mapped[str] = mapped_column(String(16), default="RISK")
    priority_level: Mapped[str] = mapped_column(String(4), index=True)
    source_structure_id: Mapped[int] = mapped_column(Integer, index=True)
    daily_state: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    structure_type: Mapped[str] = mapped_column(String(48))
    score: Mapped[float] = mapped_column(Float, default=0, index=True)
    reason: Mapped[str] = mapped_column(Text)
    next_wait: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE", index=True)


class TradePlan(Base, TimestampMixin):
    __tablename__ = "trade_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    direction: Mapped[str] = mapped_column(String(16), default="LONG")
    source_structure_id: Mapped[int] = mapped_column(Integer, index=True)
    battle_pool_id: Mapped[int] = mapped_column(Integer, index=True)
    daily_state: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    structure_type: Mapped[str] = mapped_column(String(48))
    priority_level: Mapped[str] = mapped_column(String(4), index=True)
    entry_mode: Mapped[str] = mapped_column(String(32), default="BREAKOUT")
    breakout_entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    pullback_entry_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    pullback_entry_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    low_absorb_entry_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    low_absorb_entry_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_price: Mapped[float] = mapped_column(Float)
    target_1: Mapped[float] = mapped_column(Float)
    target_2: Mapped[float] = mapped_column(Float)
    trailing_rule: Mapped[str] = mapped_column(Text)
    time_stop_rule: Mapped[str] = mapped_column(Text)
    invalid_condition: Mapped[str] = mapped_column(Text)
    risk_reward_1: Mapped[float] = mapped_column(Float)
    risk_reward_2: Mapped[float] = mapped_column(Float)
    alert_status: Mapped[str] = mapped_column(String(24), default="NOT_ARMED")
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE", index=True)
    reason: Mapped[str] = mapped_column(Text)
    no_chase_above: Mapped[float | None] = mapped_column(Float, nullable=True)
    no_chase_below: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rules_approval_status: Mapped[str] = mapped_column(String(40), default="NOT_REVIEWED", index=True)
    rules_reject_reason: Mapped[str] = mapped_column(Text, default="")
    capital_status: Mapped[str] = mapped_column(String(32), default="CAPITAL_UNKNOWN", index=True)
    capital_reason: Mapped[str] = mapped_column(Text, default="")
    activation_status: Mapped[str] = mapped_column(String(32), default="PLANNED")
    waitlist_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    simulated_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    missed_by_capital_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    missed_by_capital_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    suggested_shares: Mapped[int | None] = mapped_column(Integer, nullable=True)
    available_cash_snapshot: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_new_position_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    manual_checklist_json: Mapped[str] = mapped_column(Text, default="[]")


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
    risk_per_share: Mapped[float | None] = mapped_column(Float, nullable=True)
    allowed_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    position_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_r: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_structure_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    trigger_timeframe: Mapped[str | None] = mapped_column(String(16), nullable=True)
    trigger_ts: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    trigger_level: Mapped[float | None] = mapped_column(Float, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    script_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
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
    entry_signal_id: Mapped[int] = mapped_column(Integer, default=0, nullable=False, index=True)
    entry_price: Mapped[float] = mapped_column(Float)
    stop_price: Mapped[float] = mapped_column(Float)
    trailing_stop: Mapped[float | None] = mapped_column(Float, nullable=True)
    shares: Mapped[int] = mapped_column(Integer)
    risk_amount: Mapped[float] = mapped_column(Float)
    current_r: Mapped[float] = mapped_column(Float, default=0)
    exit_reason: Mapped[str] = mapped_column(Text, default="")
    source_trade_plan_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    entry_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exit_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_1: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_2: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_r: Mapped[float] = mapped_column(Float, default=0)
    min_r: Mapped[float] = mapped_column(Float, default=0)
    partial_exit_done: Mapped[bool] = mapped_column(Boolean, default=False)
    trailing_stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    overnight_policy: Mapped[str] = mapped_column(String(24), default="INTRADAY_ONLY")
    source: Mapped[str] = mapped_column(String(32), default="LOCAL_STRATEGY", index=True)
    is_orphan: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    available_shares: Mapped[int] = mapped_column(Integer, default=0)
    current_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_value: Mapped[float] = mapped_column(Float, default=0)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0)
    unrealized_pnl_pct: Mapped[float] = mapped_column(Float, default=0)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_verified: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    close_source: Mapped[str] = mapped_column(String(32), default="")
    take_profit_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_risk_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")


class SimOrder(Base, TimestampMixin):
    __tablename__ = "sim_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_plan_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[str] = mapped_column(String(8))
    order_type: Mapped[str] = mapped_column(String(16), default="LIMIT")
    qty: Mapped[int] = mapped_column(Integer)
    limit_price: Mapped[float] = mapped_column(Float)
    submitted_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    futu_order_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    trd_env: Mapped[str] = mapped_column(String(16), default="SIMULATE")
    status: Mapped[str] = mapped_column(String(32), default="SUBMITTED", index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    raw_response_json: Mapped[str] = mapped_column(Text, default="{}")
    dealt_qty: Mapped[int] = mapped_column(Integer, default=0)
    dealt_avg_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)


class SimDeal(Base, TimestampMixin):
    __tablename__ = "sim_deals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sim_order_id: Mapped[int] = mapped_column(Integer, index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[str] = mapped_column(String(8))
    qty: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float)
    dealt_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    futu_deal_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    raw_json: Mapped[str] = mapped_column(Text, default="{}")


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(32), default="", index=True)
    subject_type: Mapped[str] = mapped_column(String(32), default="")
    subject_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="INFO")
    reason: Mapped[str] = mapped_column(Text, default="")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")


class ReviewStat(Base, TimestampMixin):
    __tablename__ = "review_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_type: Mapped[str] = mapped_column(String(32), index=True)
    subject_id: Mapped[int] = mapped_column(Integer, index=True)
    metric: Mapped[str] = mapped_column(String(64), index=True)
    value: Mapped[float] = mapped_column(Float)


class BacktestTrade(Base, TimestampMixin):
    __tablename__ = "backtest_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    script: Mapped[str] = mapped_column(String(48), default="")
    source_structure_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    structure_type: Mapped[str] = mapped_column(String(48), default="")
    structure_ts: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    trigger_timeframe: Mapped[str] = mapped_column(String(16), default="")
    trigger_reason: Mapped[str] = mapped_column(Text, default="")
    entry_ts: Mapped[datetime] = mapped_column(DateTime, index=True)
    entry_price: Mapped[float] = mapped_column(Float)
    stop_price: Mapped[float] = mapped_column(Float)
    shares: Mapped[int] = mapped_column(Integer)
    risk_amount: Mapped[float] = mapped_column(Float)
    exit_ts: Mapped[datetime] = mapped_column(DateTime, index=True)
    exit_price: Mapped[float] = mapped_column(Float)
    exit_reason: Mapped[str] = mapped_column(Text)
    max_r: Mapped[float] = mapped_column(Float)
    min_r: Mapped[float] = mapped_column(Float)
    final_r: Mapped[float] = mapped_column(Float)
    holding_bars: Mapped[int] = mapped_column(Integer)
    market_state_at_entry: Mapped[str] = mapped_column(String(32), default="")
    stock_trend_at_entry: Mapped[str] = mapped_column(String(32), default="")


class SystemConfig(Base, TimestampMixin):
    __tablename__ = "system_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    value: Mapped[str] = mapped_column(Text, default="")


class ReconciliationIssue(Base, TimestampMixin):
    __tablename__ = "reconciliation_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), default="", index=True)
    issue_type: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(24), default="WARN", index=True)
    status: Mapped[str] = mapped_column(String(24), default="OPEN", index=True)
    remote_order_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    local_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    position_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    trade_plan_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
