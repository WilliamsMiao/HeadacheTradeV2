from datetime import datetime, timedelta

from app.domain import Bar, DAILY, HOUR_60
from app.providers.base import MarketDataProvider


class MockProvider(MarketDataProvider):
    def __init__(self, symbols: list[str] | None = None) -> None:
        self.symbols = symbols or ["AAPL", "MSFT", "NVDA", "SPY", "QQQ"]

    def get_watchlist(self) -> list[dict[str, str]]:
        return [{"symbol": symbol, "name": symbol, "industry": "Technology", "source_group": "mock"} for symbol in self.symbols if symbol not in {"SPY", "QQQ"}]

    def get_klines(self, symbol: str, timeframe: str, start: datetime | None = None, end: datetime | None = None) -> list[Bar]:
        count = 140 if timeframe == DAILY else 220
        delta = timedelta(days=1) if timeframe == DAILY else timedelta(hours=1)
        begin = datetime(2025, 1, 1, 9, 30)
        bars: list[Bar] = []
        base = 100 + len(symbol) * 3
        for index in range(count):
            trend = index * 0.28
            pullback = -8 + abs(index - 95) * 0.32 if 80 <= index <= 110 else 0
            recovery = max(0, index - 110) * 0.42
            close = base + trend + pullback + recovery
            open_price = close - 0.4
            high = close + 1.2
            low = close - 1.5
            volume = 1_000_000 + index * 5000
            bars.append(Bar(symbol=symbol, timeframe=timeframe, ts=begin + index * delta, open=open_price, high=high, low=low, close=close, volume=volume))
        return bars

