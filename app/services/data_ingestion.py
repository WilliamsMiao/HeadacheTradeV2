from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import DAILY, HOUR_60, Bar
from app.models import KLine, WatchlistItem
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


def upsert_bars(session: Session, bars: list[Bar]) -> tuple[int, int]:
    count = 0
    anomaly_count = 0
    for bar in sorted(bars, key=lambda item: item.ts):
        data_ok, reason = validate_bar(bar)
        record = session.scalar(
            select(KLine).where(KLine.symbol == bar.symbol, KLine.timeframe == bar.timeframe, KLine.ts == bar.ts)
        )
        if record is None:
            record = KLine(symbol=bar.symbol, timeframe=bar.timeframe, ts=bar.ts, open=bar.open, high=bar.high, low=bar.low, close=bar.close, volume=bar.volume)
            session.add(record)
        else:
            record.open = bar.open
            record.high = bar.high
            record.low = bar.low
            record.close = bar.close
            record.volume = bar.volume
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
) -> dict[str, str]:
    results: dict[str, str] = {}
    for symbol in symbols:
        for timeframe in (DAILY, HOUR_60):
            try:
                bars = provider.get_klines(symbol, timeframe, start, end)
                if not bars:
                    results[f"{symbol}:{timeframe}"] = "no bars returned from data source"
                    continue
                count, anomaly_count = upsert_bars(session, bars)
                if anomaly_count:
                    results[f"{symbol}:{timeframe}"] = f"updated {count} bars; {anomaly_count} anomalous bars isolated"
                else:
                    results[f"{symbol}:{timeframe}"] = f"updated {count} bars; data quality passed"
            except Exception as exc:
                results[f"{symbol}:{timeframe}"] = f"data source failed: {exc}"
    return results
