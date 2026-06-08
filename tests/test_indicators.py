from datetime import datetime, timedelta

from app.models import KLine
from app.services.indicators import calculate_indicator_rows


def test_indicators_are_time_ordered_without_future_values():
    rows = [
        KLine(symbol="AAPL", timeframe="1d", ts=datetime(2025, 1, 1) + timedelta(days=i), open=10 + i, high=11 + i, low=9 + i, close=10 + i, volume=1000 + i)
        for i in range(65)
    ]
    indicators = calculate_indicator_rows(list(reversed(rows)))
    assert indicators[18].ma20 is None
    assert indicators[19].ma20 == sum(range(10, 30)) / 20
    assert indicators[58].ma60 is None
    assert indicators[59].ma60 == sum(range(10, 70)) / 60
    assert indicators[-1].macd_dif is not None
    assert indicators[-1].atr is not None

