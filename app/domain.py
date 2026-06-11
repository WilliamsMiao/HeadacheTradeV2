from dataclasses import dataclass
from datetime import datetime


DAILY = "1d"
HOUR_60 = "60m"
MIN_15 = "15m"
MIN_5 = "5m"

TREND_TIMEFRAME = DAILY
STRUCTURE_TIMEFRAME = HOUR_60
OPTIONAL_TRIGGER_TIMEFRAME = MIN_15
OPTIONAL_DISPLAY_TIMEFRAME = MIN_5
# Backwards-compatible aliases for optional modules. They are not core dependencies.
TRIGGER_TIMEFRAME = OPTIONAL_TRIGGER_TIMEFRAME
DISPLAY_TIMEFRAME = OPTIONAL_DISPLAY_TIMEFRAME

CORE_TIMEFRAMES = (TREND_TIMEFRAME, STRUCTURE_TIMEFRAME)
DISPLAY_TIMEFRAMES = (OPTIONAL_TRIGGER_TIMEFRAME, OPTIONAL_DISPLAY_TIMEFRAME)
SUPPORTED_TIMEFRAMES = (*CORE_TIMEFRAMES, *DISPLAY_TIMEFRAMES)

TIMEFRAME_LABELS = {
    DAILY: "日线",
    HOUR_60: "60 分钟",
    MIN_15: "15 分钟",
    MIN_5: "5 分钟",
}

TIMEFRAME_STALE_DAYS = {
    DAILY: 7,
    HOUR_60: 7,
}

MARKET_STATES = {"RISK_ON", "NEUTRAL_POSITIVE", "NEUTRAL_NEGATIVE", "RISK_OFF"}
# Legacy optional modules still import these constants. The new pipeline does not
# use them to block screening, structure scanning, battle ranking, or plan creation.
TRADEABLE_MARKETS = {"RISK_ON", "NEUTRAL_POSITIVE"}
ENTRY_TRENDS = {"STRONG_UPTREND", "UPTREND"}
DAILY_STATES = {
    "DAILY_STRONG_BULL",
    "DAILY_WEAK_BULL",
    "DAILY_RANGE",
    "DAILY_WEAK_BEAR",
    "DAILY_STRONG_BEAR",
    "UNKNOWN",
}
CANDIDATE_POOL_TYPES = {
    "LOW_REBOUND",
    "TREND_UP",
    "HIGH_RISK",
    "WEAK_DOWN",
}
BATTLE_PRIORITIES = {"S", "A", "B", "C"}
TRADING_STATES = {
    "IDLE",
    "CANDIDATE_POOL",
    "STRUCTURE_DETECTED",
    "BATTLE_WATCH",
    "PLAN_READY",
    "PRICE_ALERT_ARMED",
    "ENTRY_REVIEW",
    "SIM_POSITION",
    "RISK_PROTECTION",
    "EXIT_REVIEW",
    "COOLDOWN",
}


@dataclass(frozen=True)
class Bar:
    symbol: str
    timeframe: str
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    turnover: float = 0.0


@dataclass(frozen=True)
class RiskResult:
    entry_price: float
    stop_price: float
    risk_per_share: float
    allowed_loss: float
    shares: int
    position_value: float
    position_pct: float
