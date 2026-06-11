from datetime import datetime, timedelta

import pytest

from app.models import Indicator, KLine
from app.services.daily_state import evaluate_daily_state


def seed_daily(session, close, ma20, ma60, dif, prior_ma20):
    start = datetime(2026, 6, 1)
    for index in range(6):
        current_ma20 = prior_ma20 + (ma20 - prior_ma20) * index / 5
        session.add(
            KLine(
                symbol="AAPL",
                timeframe="1d",
                ts=start + timedelta(days=index),
                open=close,
                high=close * 1.01,
                low=close * 0.99,
                close=close,
                volume=1_000_000,
                turnover=close * 1_000_000,
            )
        )
        session.add(
            Indicator(
                symbol="AAPL",
                timeframe="1d",
                ts=start + timedelta(days=index),
                ma20=current_ma20,
                ma60=ma60,
                macd_dif=dif,
                boll_mid=current_ma20,
            )
        )
    session.commit()


@pytest.mark.parametrize(
    ("close", "ma20", "ma60", "dif", "prior_ma20", "expected"),
    [
        (110, 100, 90, 2, 95, "DAILY_STRONG_BULL"),
        (101, 100, 99, -0.2, 99.5, "DAILY_WEAK_BULL"),
        (100, 100, 105, 0, 100, "DAILY_RANGE"),
        (92, 100, 98, -1, 101, "DAILY_WEAK_BEAR"),
        (80, 90, 100, -2, 95, "DAILY_STRONG_BEAR"),
    ],
)
def test_daily_state_classification(session, close, ma20, ma60, dif, prior_ma20, expected):
    seed_daily(session, close, ma20, ma60, dif, prior_ma20)
    assert evaluate_daily_state(session, "AAPL").state == expected


def test_daily_state_unknown_when_history_missing(session):
    assert evaluate_daily_state(session, "AAPL").state == "UNKNOWN"
