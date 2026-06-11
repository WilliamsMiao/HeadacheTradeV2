from dataclasses import dataclass
from datetime import datetime


DAILY = "1d"
HOUR_60 = "60m"
MIN_15 = "15m"
MIN_5 = "5m"

TREND_TIMEFRAME = DAILY
STRUCTURE_TIMEFRAME = HOUR_60
TRIGGER_TIMEFRAME = MIN_15
DISPLAY_TIMEFRAME = MIN_5

CORE_TIMEFRAMES = (TREND_TIMEFRAME, STRUCTURE_TIMEFRAME, TRIGGER_TIMEFRAME)
DISPLAY_TIMEFRAMES = (DISPLAY_TIMEFRAME,)
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
    MIN_15: 7,
}

MARKET_STATES = {"RISK_ON", "NEUTRAL_POSITIVE", "NEUTRAL_NEGATIVE", "RISK_OFF"}
TRADEABLE_MARKETS = {"RISK_ON", "NEUTRAL_POSITIVE"}
ENTRY_TRENDS = {"STRONG_UPTREND", "UPTREND"}


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


@dataclass(frozen=True)
class RiskResult:
    entry_price: float
    stop_price: float
    risk_per_share: float
    allowed_loss: float
    shares: int
    position_value: float
    position_pct: float
