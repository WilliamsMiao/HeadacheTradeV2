from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.domain import CORE_TIMEFRAMES, DISPLAY_TIMEFRAME, STRUCTURE_TIMEFRAME, TIMEFRAME_LABELS, TIMEFRAME_STALE_DAYS, TREND_TIMEFRAME
from app.models import CandidateStock, DailyState, Indicator, KLine, StructureEvent
from app.providers.futu_provider import FutuProvider
from app.providers.mock_provider import MockProvider
from app.services.battle_pool import rank_battle_pool
from app.services.daily_state import evaluate_daily_state, persist_daily_state
from app.services.data_ingestion import candidate_symbols, update_market_data
from app.services.indicators import compute_indicators_for_symbol
from app.services.market import evaluate_market, persist_market_state
from app.services.monitor_state import refresh_monitor_state
from app.services.price_alert import set_price_alerts
from app.services.screener import screen_market
from app.services.structures import detect_latest_structures, persist_structure_detections, update_structure_follow_through
from app.services.trade_plan import generate_trade_plans


def get_provider(settings: Settings, use_mock: bool = False):
    if use_mock:
        return MockProvider(["AAPL", "MSFT", "NVDA", *settings.market_symbols])
    return FutuProvider(settings)


def run_screen_market(session: Session, settings: Settings, use_mock: bool = False) -> dict[str, object]:
    provider = get_provider(settings, use_mock)
    try:
        if use_mock and not hasattr(provider, "get_stock_filter_candidates"):
            raise RuntimeError("测试数据源未实现条件选股")
        return screen_market(session, provider)
    finally:
        close = getattr(provider, "close", None)
        if close:
            close()


def run_sync_watchlist(session: Session, settings: Settings, use_mock: bool = False) -> int:
    """Legacy command name: it now refreshes the system candidate pool."""
    return int(run_screen_market(session, settings, use_mock)["selected"])


def run_update_market_data(
    session: Session,
    settings: Settings,
    use_mock: bool = False,
    on_progress: Callable[[int, int, str], None] | None = None,
    timeframes: tuple[str, ...] | None = None,
) -> dict[str, object]:
    provider = get_provider(settings, use_mock)
    try:
        symbols = candidate_symbols(session, include_market=settings.market_symbols)
        if len(symbols) == len(settings.market_symbols) and not use_mock:
            screen_market(session, provider)
            symbols = candidate_symbols(session, include_market=settings.market_symbols)
        details = update_market_data(
            session,
            provider,
            symbols,
            include_display_timeframes=False,
            timeframes=timeframes,
            on_progress=on_progress,
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


def run_compute_indicators(
    session: Session,
    settings: Settings,
    timeframes: tuple[str, ...] = CORE_TIMEFRAMES,
) -> int:
    count = 0
    for symbol in candidate_symbols(session, include_market=settings.market_symbols):
        for timeframe in timeframes:
            count += compute_indicators_for_symbol(session, symbol, timeframe)
    return count


def run_scan_structures(session: Session, settings: Settings) -> dict[str, int]:
    structures = 0
    daily_states = 0
    symbols = [
        symbol
        for symbol in candidate_symbols(session)
        if symbol not in settings.market_symbols
    ]
    market_eval = evaluate_market(session, settings.market_symbols)
    persist_market_state(session, market_eval)
    for symbol in symbols:
        data_ok, _ = symbol_data_status(session, symbol)
        if not data_ok:
            continue
        daily_eval = evaluate_daily_state(session, symbol)
        if daily_eval.as_of is not None:
            persist_daily_state(session, daily_eval)
            daily_states += 1
        detections = detect_latest_structures(session, symbol, STRUCTURE_TIMEFRAME)
        records = persist_structure_detections(
            session,
            detections,
            market_eval.state,
            daily_eval.state,
        )
        structures += len(records)
    update_structure_follow_through(session)
    return {"daily_states": daily_states, "structures": structures}


def run_pipeline(session: Session, settings: Settings) -> dict[str, object]:
    scan = run_scan_structures(session, settings)
    battle = rank_battle_pool(session)
    plans = generate_trade_plans(session)
    states = 0
    for symbol in candidate_symbols(session):
        refresh_monitor_state(session, symbol)
        states += 1
    market = evaluate_market(session, settings.market_symbols)
    return {
        **scan,
        "battle_pool": battle,
        "trade_plans": plans,
        "states": states,
        "market_state": market.state,
        "market_is_advisory": True,
    }


def run_daily(
    session: Session,
    settings: Settings,
    use_mock: bool = False,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> dict[str, object]:
    screening = run_screen_market(session, settings, use_mock)
    market_data = run_update_market_data(session, settings, use_mock, on_progress)
    indicators = run_compute_indicators(session, settings)
    pipeline = run_pipeline(session, settings)
    return {
        "screening": screening,
        "market_data": market_data,
        "indicators": indicators,
        "pipeline": pipeline,
    }


def run_60m(
    session: Session,
    settings: Settings,
    use_mock: bool = False,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> dict[str, object]:
    market_data = run_update_market_data(
        session,
        settings,
        use_mock,
        timeframes=(STRUCTURE_TIMEFRAME,),
        on_progress=on_progress,
    )
    indicators = run_compute_indicators(session, settings, timeframes=(STRUCTURE_TIMEFRAME,))
    pipeline = run_pipeline(session, settings)
    return {"market_data": market_data, "indicators": indicators, "pipeline": pipeline}


def run_set_price_alerts(
    session: Session,
    settings: Settings,
    use_mock: bool = False,
) -> dict[str, object]:
    if use_mock:
        raise RuntimeError("模拟数据源不设置 Futu 到价提醒")
    provider = get_provider(settings, use_mock=False)
    try:
        return set_price_alerts(session, provider)
    finally:
        provider.close()


def run_full_refresh(session: Session, settings: Settings, use_mock: bool = False) -> dict[str, object]:
    return run_daily(session, settings, use_mock)


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
            return False, (
                f"{timeframe} data stale at {bar.ts:%Y-%m-%d}; "
                f"latest daily bar is {trend_bar.ts:%Y-%m-%d}"
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
