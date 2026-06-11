from abc import ABC, abstractmethod
from datetime import datetime

from app.domain import Bar


class MarketDataProvider(ABC):
    def get_stock_filter_candidates(self) -> list[dict[str, object]]:
        raise NotImplementedError

    def get_market_snapshot(self, symbols: list[str]) -> list[dict[str, object]]:
        raise NotImplementedError

    def set_price_reminder(
        self,
        symbol: str,
        reminder_type: str,
        value: float,
        note: str,
    ) -> int:
        raise NotImplementedError

    def get_price_reminders(self, symbol: str) -> list[dict[str, object]]:
        raise NotImplementedError

    @abstractmethod
    def get_klines(self, symbol: str, timeframe: str, start: datetime | None = None, end: datetime | None = None) -> list[Bar]:
        raise NotImplementedError
