from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.domain import (
    CORE_TIMEFRAMES,
    DISPLAY_TIMEFRAME,
    STRUCTURE_TIMEFRAME,
    TIMEFRAME_LABELS,
    TIMEFRAME_STALE_DAYS,
    TREND_TIMEFRAME,
)
from app.models import Indicator, KLine, TradeSignal
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
    provider = get_provider(settings, use_mock)
    try:
        return sync_watchlist(session, provider)
    finally:
        close = getattr(provider, "close", None)
        if close:
            close()


def run_update_market_data(session: Session, settings: Settings, use_mock: bool = False) -> dict[str, object]:
    provider = get_provider(settings, use_mock)
    try:
        symbols = list(dict.fromkeys([*settings.market_symbols, *active_symbols(session)]))
        if not symbols:
            sync_watchlist(session, provider)
            symbols = list(dict.fromkeys([*settings.market_symbols, *active_symbols(session)]))
        details = update_market_data(
            session,
            provider,
            symbols,
            include_display_timeframes=settings.futu_include_5m,
        )
        failures = {
            key: value
            for key, value in details.items()
            if value.startswith("data source failed:") or value == "no bars returned from data source"
        }
        anomalous = {key: value for key, value in details.items() if "anomalous bars isolated" in value}
        return {
            "updated": len(details) - len(failures),
            "failed": len(failures),
            "anomalous": len(anomalous),
            "failures": failures,
            "details": details,
        }
    finally:
        close = getattr(provider, "close", None)
        if close:
            close()


def run_compute_indicators(session: Session, settings: Settings) -> int:
    symbols = active_symbols(session, include_market=settings.market_symbols)
    count = 0
    for symbol in symbols:
        for timeframe in CORE_TIMEFRAMES:
            count += compute_indicators_for_symbol(session, symbol, timeframe)
    return count


def run_pipeline(session: Session, settings: Settings) -> dict[str, int | str]:
    market_eval = evaluate_market(session, settings.market_symbols)
    persist_market_state(session, market_eval)
    counts = {"structures": 0, "states": 0, "signals": 0, "market_state": market_eval.state}
    symbols = [symbol for symbol in active_symbols(session) if symbol not in settings.market_symbols]
    for symbol in symbols:
        data_ok, data_reason = symbol_data_status(session, symbol)
        if not data_ok:
            state = advance_state_machine(session, symbol, "RISK_OFF", "UNKNOWN")
            state.last_reason = data_reason
            state.next_wait = "repair market data, recompute indicators, then rerun pipeline"
            session.commit()
            counts["states"] += 1
            continue
        trend_eval = evaluate_stock_trend(session, symbol)
        persist_stock_trend(session, trend_eval)
        detections = detect_latest_structures(session, symbol, STRUCTURE_TIMEFRAME)
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


def symbol_data_status(session: Session, symbol: str) -> tuple[bool, str]:
    latest_bars: dict[str, KLine] = {}
    for timeframe in CORE_TIMEFRAMES:
        bar = session.scalar(
            select(KLine)
            .where(KLine.symbol == symbol, KLine.timeframe == timeframe)
            .order_by(KLine.ts.desc())
            .limit(1)
        )
        timeframe_label = "daily" if timeframe == TREND_TIMEFRAME else timeframe
        if bar is None:
            return False, f"{timeframe_label} data missing"
        if not bar.data_ok:
            return False, bar.anomaly_reason or f"{timeframe_label} data anomaly"
        latest_bars[timeframe] = bar

        indicator = session.scalar(
            select(Indicator).where(
                Indicator.symbol == symbol,
                Indicator.timeframe == timeframe,
                Indicator.ts == bar.ts,
            )
        )
        if indicator is None:
            return False, f"{timeframe_label} indicators missing at {bar.ts:%Y-%m-%d %H:%M}"

    trend_bar = latest_bars[TREND_TIMEFRAME]
    for timeframe in CORE_TIMEFRAMES:
        bar = latest_bars[timeframe]
        if (trend_bar.ts.date() - bar.ts.date()).days > TIMEFRAME_STALE_DAYS[timeframe]:
            return (
                False,
                f"{timeframe} data stale at {bar.ts:%Y-%m-%d}; "
                f"latest daily bar is {trend_bar.ts:%Y-%m-%d}",
            )
    return True, "data quality passed"


def display_data_status(session: Session, symbol: str) -> tuple[bool, str]:
    bar = session.scalar(
        select(KLine)
        .where(KLine.symbol == symbol, KLine.timeframe == DISPLAY_TIMEFRAME)
        .order_by(KLine.ts.desc())
        .limit(1)
    )
    if bar is None:
        return False, f"{TIMEFRAME_LABELS[DISPLAY_TIMEFRAME]} data missing; core trading is not blocked"
    if not bar.data_ok:
        return False, bar.anomaly_reason or f"{TIMEFRAME_LABELS[DISPLAY_TIMEFRAME]} data anomaly"
    return True, "display data available"


def _pending_signal_count(session: Session) -> int:
    return len(list(session.scalars(select(TradeSignal).where(TradeSignal.status == "PENDING"))))
