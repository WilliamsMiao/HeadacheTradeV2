from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import CORE_TIMEFRAMES, DISPLAY_TIMEFRAMES, Bar
from app.models import CandidateStock, KLine, WatchlistItem
from app.providers.base import MarketDataProvider
from app.services.data_quality import validate_bar


def sync_watchlist(session: Session, provider: MarketDataProvider) -> int:
    rows = provider.get_watchlist()
    seen: set[str] = set()
    count = 0
    for row in rows:
        symbol = row["symbol"].upper()
        seen.add(symbol)
        item = session.scalar(select(WatchlistItem).where(WatchlistItem.symbol == symbol))
        if item is None:
            item = WatchlistItem(symbol=symbol)
            session.add(item)
        item.name = row.get("name", symbol)
        item.industry = row.get("industry", "")
        item.source_group = row.get("source_group", "")
        item.active = True
        count += 1
    for item in session.scalars(select(WatchlistItem).where(WatchlistItem.active.is_(True))):
        if item.symbol not in seen:
            item.active = False
    session.commit()
    return count


def active_symbols(session: Session, include_market: list[str] | None = None) -> list[str]:
    symbols = [item.symbol for item in session.scalars(select(WatchlistItem).where(WatchlistItem.active.is_(True)).order_by(WatchlistItem.symbol))]
    for symbol in include_market or []:
        if symbol not in symbols:
            symbols.append(symbol)
    return symbols


def candidate_symbols(session: Session, include_market: list[str] | None = None) -> list[str]:
    symbols = list(
        session.scalars(
            select(CandidateStock.symbol)
            .where(CandidateStock.active.is_(True))
            .order_by(CandidateStock.rank_score.desc(), CandidateStock.symbol)
        )
    )
    for symbol in include_market or []:
        if symbol not in symbols:
            symbols.append(symbol)
    return symbols


def upsert_bars(session: Session, bars: list[Bar]) -> tuple[int, int]:
    count = 0
    anomaly_count = 0
    for bar in sorted(bars, key=lambda item: item.ts):
        data_ok, reason = validate_bar(bar)
        record = session.scalar(
            select(KLine).where(KLine.symbol == bar.symbol, KLine.timeframe == bar.timeframe, KLine.ts == bar.ts)
        )
        if record is None:
            record = KLine(
                symbol=bar.symbol,
                timeframe=bar.timeframe,
                ts=bar.ts,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                turnover=bar.turnover,
            )
            session.add(record)
        else:
            record.open = bar.open
            record.high = bar.high
            record.low = bar.low
            record.close = bar.close
            record.volume = bar.volume
            record.turnover = bar.turnover
        record.data_ok = data_ok
        record.anomaly_reason = "" if data_ok else reason
        count += 1
        anomaly_count += int(not data_ok)
    session.commit()
    return count, anomaly_count


def update_market_data(
    session: Session,
    provider: MarketDataProvider,
    symbols: list[str],
    start: datetime | None = None,
    end: datetime | None = None,
    include_display_timeframes: bool = False,
    timeframes: tuple[str, ...] | None = None,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> dict[str, str]:
    results: dict[str, str] = {}
    selected_timeframes = timeframes or (
        (*CORE_TIMEFRAMES, *DISPLAY_TIMEFRAMES) if include_display_timeframes else CORE_TIMEFRAMES
    )
    total = len(symbols) * len(selected_timeframes)
    completed = 0
    for symbol in symbols:
        for timeframe in selected_timeframes:
            key = f"{symbol}:{timeframe}"
            try:
                bars = provider.get_klines(symbol, timeframe, start, end)
                if not bars:
                    results[key] = "no bars returned from data source"
                    continue
                count, anomaly_count = upsert_bars(session, bars)
                if anomaly_count:
                    results[key] = f"updated {count} bars; {anomaly_count} anomalous bars isolated"
                else:
                    results[key] = f"updated {count} bars; data quality passed"
            except Exception as exc:
                results[key] = f"data source failed: {exc}"
            finally:
                completed += 1
                if on_progress:
                    on_progress(completed, total, f"正在更新 {symbol} · {timeframe}")
    return results
