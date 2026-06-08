from dataclasses import dataclass
from datetime import datetime


DAILY = "1d"
HOUR_60 = "60m"

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

