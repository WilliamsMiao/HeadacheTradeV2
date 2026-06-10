from types import SimpleNamespace

import pytest

from app.config import Settings
from app.domain import (
    CORE_TIMEFRAMES,
    DAILY,
    DISPLAY_TIMEFRAMES,
    HOUR_60,
    MIN_15,
    MIN_5,
    STRUCTURE_TIMEFRAME,
    TRIGGER_TIMEFRAME,
    TREND_TIMEFRAME,
)
from app.providers.futu_provider import FutuProvider
from app.providers.mock_provider import MockProvider
from app.services.data_ingestion import update_market_data
from app.services.pipeline import display_data_status


def test_timeframe_roles_are_explicit():
    assert CORE_TIMEFRAMES == ("1d", "60m", "15m")
    assert DISPLAY_TIMEFRAMES == ("5m",)
    assert TREND_TIMEFRAME == DAILY
    assert STRUCTURE_TIMEFRAME == HOUR_60
    assert TRIGGER_TIMEFRAME == MIN_15


def test_futu_timeframe_mapping_supports_all_declared_frames():
    fake = SimpleNamespace(K_DAY="day", K_60M="60", K_15M="15", K_5M="5")
    assert FutuProvider._kline_type(fake, DAILY) == "day"
    assert FutuProvider._kline_type(fake, HOUR_60) == "60"
    assert FutuProvider._kline_type(fake, MIN_15) == "15"
    assert FutuProvider._kline_type(fake, MIN_5) == "5"
    with pytest.raises(ValueError, match="unsupported Futu timeframe"):
        FutuProvider._kline_type(fake, "2m")


def test_mock_provider_supports_core_and_display_timeframes():
    provider = MockProvider(["AAPL"])
    for timeframe in (*CORE_TIMEFRAMES, *DISPLAY_TIMEFRAMES):
        bars = provider.get_klines("AAPL", timeframe)
        assert len(bars) >= 100
        assert {bar.timeframe for bar in bars} == {timeframe}


def test_display_timeframe_is_optional(session):
    provider = MockProvider(["AAPL"])
    core_results = update_market_data(session, provider, ["AAPL"])
    assert "AAPL:15m" in core_results
    assert "AAPL:5m" not in core_results
    assert display_data_status(session, "AAPL")[0] is False

    display_results = update_market_data(session, provider, ["AAPL"], include_display_timeframes=True)
    assert "AAPL:5m" in display_results
    assert display_data_status(session, "AAPL") == (True, "display data available")


def test_5m_collection_is_disabled_by_default():
    assert Settings().futu_include_5m is False
