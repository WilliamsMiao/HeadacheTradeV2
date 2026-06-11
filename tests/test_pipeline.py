from app.config import get_settings
from app.models import CandidateStock, TradeSignal
from app.services.pipeline import run_60m, run_full_refresh, run_pipeline
from sqlalchemy import select


def test_mock_full_refresh_runs_closed_loop(session):
    settings = get_settings()
    result = run_full_refresh(session, settings, use_mock=True)
    assert result["screening"]["selected"] >= 1
    assert result["indicators"] > 0
    assert "market_state" in result["pipeline"]
    assert session.scalar(select(CandidateStock).where(CandidateStock.symbol == "AAPL")) is not None


def test_market_state_is_advisory_and_does_not_create_direct_entry_signal(session):
    run_full_refresh(session, get_settings(), use_mock=True)
    settings = get_settings()
    result = run_pipeline(session, settings)
    assert result["states"] >= 1
    assert result["market_is_advisory"] is True
    pending_entries = list(session.scalars(select(TradeSignal).where(TradeSignal.symbol == "AAPL", TradeSignal.signal_type == "ENTRY")))
    assert not pending_entries


def test_60m_refresh_only_updates_structure_timeframe(session, monkeypatch):
    captured = {}

    def fake_update(session, settings, use_mock=False, on_progress=None, timeframes=None):
        captured["market_timeframes"] = timeframes
        return {"updated": 1}

    def fake_indicators(session, settings, timeframes=("1d", "60m")):
        captured["indicator_timeframes"] = timeframes
        return 1

    monkeypatch.setattr("app.services.pipeline.run_update_market_data", fake_update)
    monkeypatch.setattr("app.services.pipeline.run_compute_indicators", fake_indicators)
    monkeypatch.setattr("app.services.pipeline.run_pipeline", lambda session, settings: {"structures": 0})

    run_60m(session, get_settings(), use_mock=True)

    assert captured["market_timeframes"] == ("60m",)
    assert captured["indicator_timeframes"] == ("60m",)
