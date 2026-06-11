from datetime import datetime

from sqlalchemy import select

from app.domain import Bar
from app.models import KLine
from app.providers.base import MarketDataProvider
from app.services.data_ingestion import update_market_data
from app.services.indicators import compute_indicators_for_symbol
from app.services.pipeline import symbol_data_status


class FixedProvider(MarketDataProvider):
    def get_watchlist(self) -> list[dict[str, str]]:
        return []

    def get_klines(self, symbol, timeframe, start=None, end=None):
        return [
            Bar(symbol, timeframe, datetime(2026, 6, 8, 10, 30), 10, 11, 9, 10.5, 100),
            Bar(symbol, timeframe, datetime(2026, 6, 9, 10, 30), 10.5, 11, 10, 10.8, 0),
            Bar(symbol, timeframe, datetime(2026, 6, 10, 10, 30), 10.8, 12, 10.5, 11.5, 120),
        ]


def test_anomalous_bar_does_not_mark_whole_batch_bad(session):
    results = update_market_data(session, FixedProvider(), ["AAPL"])

    daily = list(session.scalars(select(KLine).where(KLine.symbol == "AAPL", KLine.timeframe == "1d").order_by(KLine.ts)))
    assert [bar.data_ok for bar in daily] == [True, False, True]
    assert "1 anomalous bars isolated" in results["AAPL:1d"]
    assert "AAPL:15m" in results
    for timeframe in ("1d", "60m", "15m"):
        compute_indicators_for_symbol(session, "AAPL", timeframe)
    assert symbol_data_status(session, "AAPL") == (True, "data quality passed")


def test_stale_intraday_data_is_reported_precisely(session):
    session.add_all(
        [
            KLine(
                symbol="AAPL",
                timeframe="1d",
                ts=datetime(2026, 6, 10),
                open=10,
                high=11,
                low=9,
                close=10,
                volume=100,
            ),
            KLine(
                symbol="AAPL",
                timeframe="60m",
                ts=datetime(2026, 1, 6, 10, 30),
                open=10,
                high=11,
                low=9,
                close=10,
                volume=100,
            ),
            KLine(
                symbol="AAPL",
                timeframe="15m",
                ts=datetime(2026, 6, 10, 15, 45),
                open=10,
                high=11,
                low=9,
                close=10,
                volume=100,
            ),
        ]
    )
    session.commit()
    for timeframe in ("1d", "60m", "15m"):
        compute_indicators_for_symbol(session, "AAPL", timeframe)

    ok, reason = symbol_data_status(session, "AAPL")
    assert ok is False
    assert reason == "60m data stale at 2026-01-06; latest daily bar is 2026-06-10"
