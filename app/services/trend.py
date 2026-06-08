from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import DAILY, HOUR_60
from app.models import Indicator, KLine, StockTrend


@dataclass(frozen=True)
class TrendEvaluation:
    symbol: str
    trend: str
    reason: str


def _latest(session: Session, symbol: str, timeframe: str) -> tuple[KLine, Indicator] | None:
    kline = session.scalar(
        select(KLine)
        .where(KLine.symbol == symbol, KLine.timeframe == timeframe, KLine.data_ok.is_(True))
        .order_by(KLine.ts.desc())
        .limit(1)
    )
    if not kline:
        return None
    indicator = session.scalar(
        select(Indicator).where(Indicator.symbol == symbol, Indicator.timeframe == timeframe, Indicator.ts == kline.ts)
    )
    if not indicator:
        return None
    return kline, indicator


def evaluate_stock_trend(session: Session, symbol: str) -> TrendEvaluation:
    daily = _latest(session, symbol, DAILY)
    hour = _latest(session, symbol, HOUR_60)
    if daily is None or hour is None:
        return TrendEvaluation(symbol, "UNKNOWN", "daily or 60m data missing")
    daily_bar, daily_i = daily
    hour_bar, hour_i = hour
    required = [daily_i.ma20, daily_i.ma60, daily_i.macd_dif, hour_i.ma20, hour_i.ma60]
    if any(value is None for value in required):
        return TrendEvaluation(symbol, "UNKNOWN", "indicator history insufficient")
    daily_bull = daily_bar.close > daily_i.ma60 and daily_i.ma20 > daily_i.ma60
    hourly_not_bear = hour_bar.close >= hour_i.ma60 or hour_i.ma20 >= hour_i.ma60
    macd_not_deep = daily_i.macd_dif is not None and daily_i.macd_dif > -abs(daily_bar.close) * 0.02
    if daily_bull and hourly_not_bear and daily_bar.close > daily_i.ma20 and daily_i.macd_dif and daily_i.macd_dif > 0:
        trend = "STRONG_UPTREND"
    elif daily_bull and hourly_not_bear and macd_not_deep:
        trend = "UPTREND"
    elif daily_bar.close < daily_i.ma60 and daily_i.ma20 < daily_i.ma60:
        trend = "DOWNTREND"
    else:
        trend = "SIDEWAYS"
    reason = (
        f"daily close={daily_bar.close:.2f}, MA20={daily_i.ma20:.2f}, MA60={daily_i.ma60:.2f}; "
        f"60m close={hour_bar.close:.2f}, MA20={hour_i.ma20:.2f}, MA60={hour_i.ma60:.2f}"
    )
    return TrendEvaluation(symbol, trend, reason)


def persist_stock_trend(session: Session, evaluation: TrendEvaluation) -> StockTrend:
    latest_bar = session.scalar(
        select(KLine)
        .where(KLine.symbol == evaluation.symbol, KLine.timeframe == DAILY)
        .order_by(KLine.ts.desc())
        .limit(1)
    )
    as_of = latest_bar.ts.date() if latest_bar else None
    if as_of is None:
        raise ValueError(f"cannot persist trend for {evaluation.symbol}: no daily bar")
    record = session.scalar(select(StockTrend).where(StockTrend.symbol == evaluation.symbol, StockTrend.as_of == as_of))
    if record is None:
        record = StockTrend(symbol=evaluation.symbol, as_of=as_of, trend=evaluation.trend, reason=evaluation.reason)
        session.add(record)
    else:
        record.trend = evaluation.trend
        record.reason = evaluation.reason
    session.commit()
    return record

