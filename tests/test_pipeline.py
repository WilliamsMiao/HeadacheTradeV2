from app.config import get_settings
from app.models import TradeSignal, TradingState, WatchlistItem
from app.services.data_ingestion import sync_watchlist, update_market_data
from app.services.indicators import compute_indicators_for_symbol
from app.services.market import evaluate_market, persist_market_state
from app.services.pipeline import run_full_refresh, run_pipeline
from app.providers.mock_provider import MockProvider
from app.domain import CORE_TIMEFRAMES
from sqlalchemy import select


def test_mock_full_refresh_runs_closed_loop(session):
    settings = get_settings()
    result = run_full_refresh(session, settings, use_mock=True)
    assert result["watchlist"] >= 1
    assert result["indicators"] > 0
    assert "market_state" in result["pipeline"]
    assert session.scalar(select(WatchlistItem).where(WatchlistItem.symbol == "AAPL")) is not None


def test_risk_off_blocks_entry_candidate(session):
    provider = MockProvider(["AAPL", "SPY", "QQQ"])
    sync_watchlist(session, provider)
    update_market_data(session, provider, ["AAPL", "SPY", "QQQ"])
    for symbol in ["AAPL", "SPY", "QQQ"]:
        for timeframe in CORE_TIMEFRAMES:
            compute_indicators_for_symbol(session, symbol, timeframe)
    state = TradingState(symbol="AAPL", state="WAIT_ENTRY_TRIGGER")
    session.add(state)
    session.commit()
    settings = get_settings()
    result = run_pipeline(session, settings)
    assert result["states"] >= 1
    pending_entries = list(session.scalars(select(TradeSignal).where(TradeSignal.symbol == "AAPL", TradeSignal.signal_type == "ENTRY")))
    if result["market_state"] == "RISK_OFF":
        assert not pending_entries
