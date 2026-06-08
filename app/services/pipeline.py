from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.domain import DAILY, HOUR_60
from app.models import KLine, TradeSignal
from app.providers.futu_provider import FutuProvider
from app.providers.mock_provider import MockProvider
from app.services.data_ingestion import active_symbols, sync_watchlist, update_market_data
from app.services.indicators import compute_indicators_for_symbol
from app.services.market import evaluate_market, persist_market_state
from app.services.state_machine import advance_state_machine
from app.services.structures import detect_latest_structures, persist_structure_detections, update_structure_follow_through
from app.services.trend import evaluate_stock_trend, persist_stock_trend


def get_provider(settings: Settings, use_mock: bool = False):
    if use_mock:
        mock_symbols = ["AAPL", "MSFT", "NVDA", *settings.market_symbols]
        return MockProvider(list(dict.fromkeys(mock_symbols)))
    return FutuProvider(settings)


def run_sync_watchlist(session: Session, settings: Settings, use_mock: bool = False) -> int:
    return sync_watchlist(session, get_provider(settings, use_mock))


def run_update_market_data(session: Session, settings: Settings, use_mock: bool = False) -> dict[str, str]:
    provider = get_provider(settings, use_mock)
    symbols = active_symbols(session, include_market=settings.market_symbols)
    if not symbols:
        sync_watchlist(session, provider)
        symbols = active_symbols(session, include_market=settings.market_symbols)
    return update_market_data(session, provider, symbols)


def run_compute_indicators(session: Session, settings: Settings) -> int:
    symbols = active_symbols(session, include_market=settings.market_symbols)
    count = 0
    for symbol in symbols:
        for timeframe in (DAILY, HOUR_60):
            count += compute_indicators_for_symbol(session, symbol, timeframe)
    return count


def run_pipeline(session: Session, settings: Settings) -> dict[str, int | str]:
    market_eval = evaluate_market(session, settings.market_symbols)
    persist_market_state(session, market_eval)
    counts = {"structures": 0, "states": 0, "signals": 0, "market_state": market_eval.state}
    symbols = [symbol for symbol in active_symbols(session) if symbol not in settings.market_symbols]
    for symbol in symbols:
        data_ok = _symbol_data_ok(session, symbol)
        if not data_ok:
            state = advance_state_machine(session, symbol, "RISK_OFF", "UNKNOWN")
            state.last_reason = "data anomaly freezes new signals"
            session.commit()
            counts["states"] += 1
            continue
        trend_eval = evaluate_stock_trend(session, symbol)
        persist_stock_trend(session, trend_eval)
        detections = detect_latest_structures(session, symbol, DAILY) + detect_latest_structures(session, symbol, HOUR_60)
        records = persist_structure_detections(session, detections, market_eval.state, trend_eval.trend)
        counts["structures"] += len(records)
        advance_state_machine(session, symbol, market_eval.state, trend_eval.trend)
        counts["states"] += 1
    update_structure_follow_through(session)
    counts["signals"] = session.scalar(select(TradeSignal).where(TradeSignal.status == "PENDING").count()) if False else _pending_signal_count(session)
    return counts


def run_full_refresh(session: Session, settings: Settings, use_mock: bool = False) -> dict[str, object]:
    watchlist = run_sync_watchlist(session, settings, use_mock)
    market_data = run_update_market_data(session, settings, use_mock)
    indicators = run_compute_indicators(session, settings)
    pipeline = run_pipeline(session, settings)
    return {"watchlist": watchlist, "market_data": market_data, "indicators": indicators, "pipeline": pipeline}


def _symbol_data_ok(session: Session, symbol: str) -> bool:
    for timeframe in (DAILY, HOUR_60):
        bar = session.scalar(
            select(KLine)
            .where(KLine.symbol == symbol, KLine.timeframe == timeframe)
            .order_by(KLine.ts.desc())
            .limit(1)
        )
        if bar is None or not bar.data_ok:
            return False
    return True


def _pending_signal_count(session: Session) -> int:
    return len(list(session.scalars(select(TradeSignal).where(TradeSignal.status == "PENDING"))))
