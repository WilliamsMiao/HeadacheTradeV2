from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import DAILY
from app.models import Indicator, KLine, MarketState


@dataclass(frozen=True)
class MarketEvaluation:
    as_of: date
    state: str
    reason: str


def _latest_joined(session: Session, symbol: str) -> tuple[KLine, Indicator] | None:
    kline = session.scalar(
        select(KLine)
        .where(KLine.symbol == symbol, KLine.timeframe == DAILY, KLine.data_ok.is_(True))
        .order_by(KLine.ts.desc())
        .limit(1)
    )
    if not kline:
        return None
    indicator = session.scalar(
        select(Indicator).where(Indicator.symbol == symbol, Indicator.timeframe == DAILY, Indicator.ts == kline.ts)
    )
    if not indicator:
        return None
    return kline, indicator


def evaluate_market(session: Session, symbols: list[str]) -> MarketEvaluation:
    checks = []
    reasons = []
    latest_dates: list[date] = []
    for symbol in symbols:
        joined = _latest_joined(session, symbol)
        if joined is None:
            return MarketEvaluation(date.today(), "RISK_OFF", f"{symbol} market data or indicators missing")
        kline, indicator = joined
        latest_dates.append(kline.ts.date())
        if indicator.ma60 is None or indicator.ma20 is None or indicator.macd_dif is None:
            return MarketEvaluation(kline.ts.date(), "RISK_OFF", f"{symbol} market indicators insufficient")
        above_ma60 = kline.close > indicator.ma60
        ma_bullish = indicator.ma20 >= indicator.ma60
        macd_ok = indicator.macd_dif >= 0 or kline.close >= indicator.ma20
        checks.append(above_ma60 and ma_bullish and macd_ok)
        reasons.append(
            f"{symbol}: close {'>' if above_ma60 else '<='} MA60, MA20 {'>=' if ma_bullish else '<'} MA60, MACD {'ok' if macd_ok else 'weak'}"
        )
    strong_count = sum(1 for item in checks if item)
    as_of = max(latest_dates) if latest_dates else date.today()
    if strong_count == len(checks):
        state = "RISK_ON"
    elif strong_count >= 1:
        state = "NEUTRAL_POSITIVE"
    else:
        state = "RISK_OFF"
    return MarketEvaluation(as_of, state, "; ".join(reasons))


def persist_market_state(session: Session, evaluation: MarketEvaluation) -> MarketState:
    record = session.scalar(select(MarketState).where(MarketState.as_of == evaluation.as_of))
    if record is None:
        record = MarketState(as_of=evaluation.as_of, state=evaluation.state, reason=evaluation.reason)
        session.add(record)
    else:
        record.state = evaluation.state
        record.reason = evaluation.reason
    session.commit()
    return record

