from abc import ABC, abstractmethod
from datetime import datetime

from app.domain import Bar


class MarketDataProvider(ABC):
    @abstractmethod
    def get_watchlist(self) -> list[dict[str, str]]:
        raise NotImplementedError

    @abstractmethod
    def get_klines(self, symbol: str, timeframe: str, start: datetime | None = None, end: datetime | None = None) -> list[Bar]:
        raise NotImplementedError

