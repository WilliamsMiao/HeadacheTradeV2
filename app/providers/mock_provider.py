from datetime import datetime, timedelta

from app.domain import Bar, DAILY, HOUR_60, MIN_15, MIN_5, SUPPORTED_TIMEFRAMES
from app.providers.base import MarketDataProvider


class MockProvider(MarketDataProvider):
    def __init__(self, symbols: list[str] | None = None) -> None:
        self.symbols = symbols or ["AAPL", "MSFT", "NVDA", "SPY", "QQQ"]

    def get_watchlist(self) -> list[dict[str, str]]:
        return [{"symbol": symbol, "name": symbol, "industry": "Technology", "source_group": "mock"} for symbol in self.symbols if symbol not in {"SPY", "QQQ"}]

    def get_stock_filter_candidates(self) -> list[dict[str, object]]:
        rows = []
        pools = ("LOW_REBOUND", "TREND_UP", "HIGH_RISK", "WEAK_DOWN")
        tags = ("MACD_LOW_IMPROVING", "MA_ALIGNMENT_LONG", "MACD_TOP_DIVERGENCE", "MA_ALIGNMENT_SHORT")
        for index, symbol in enumerate(item for item in self.symbols if item not in {"SPY", "QQQ"}):
            rows.append(
                {
                    "symbol": symbol,
                    "name": symbol,
                    "market": "US",
                    "pool_type": pools[index % len(pools)],
                    "tag": tags[index % len(tags)],
                    "cur_price": 100 + index,
                    "market_val": 50_000_000_000,
                    "turnover_3d": 100_000_000 + index * 10_000_000,
                    "volume_ratio": 1.2 + index * 0.1,
                }
            )
        return rows

    def get_klines(self, symbol: str, timeframe: str, start: datetime | None = None, end: datetime | None = None) -> list[Bar]:
        if timeframe not in SUPPORTED_TIMEFRAMES:
            raise ValueError(f"unsupported mock timeframe: {timeframe}")
        count_by_timeframe = {
            DAILY: 140,
            HOUR_60: 240,
            MIN_15: 320,
            MIN_5: 360,
        }
        delta_by_timeframe = {
            DAILY: timedelta(days=1),
            HOUR_60: timedelta(hours=1),
            MIN_15: timedelta(minutes=15),
            MIN_5: timedelta(minutes=5),
        }
        count = count_by_timeframe[timeframe]
        delta = delta_by_timeframe[timeframe]
        end_anchor = datetime(2026, 6, 10, 16, 0)
        begin = end_anchor - (count - 1) * delta
        bars: list[Bar] = []
        base = 100 + len(symbol) * 3
        for index in range(count):
            progress = index / max(count - 1, 1)
            trend = index * (0.28 if timeframe == DAILY else 0.08)
            pullback = -8 + abs(progress - 0.68) * 70 if 0.56 <= progress <= 0.78 else 0
            recovery = max(0, progress - 0.78) * 55
            topping = -max(0, progress - 0.93) * 30
            close = base + trend + pullback + recovery + topping
            open_price = close - 0.4
            high = close + 1.2
            low = close - 1.5
            volume = 1_000_000 + index * 5000
            bars.append(
                Bar(
                    symbol=symbol,
                    timeframe=timeframe,
                    ts=begin + index * delta,
                    open=open_price,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                    turnover=close * volume,
                )
            )
        return bars
