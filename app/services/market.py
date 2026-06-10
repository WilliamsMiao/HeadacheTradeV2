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


@dataclass(frozen=True)
class MarketSymbolDiagnostic:
    symbol: str
    ready: bool
    passed: bool
    as_of: date | None
    close: float | None
    ma20: float | None
    ma60: float | None
    macd_dif: float | None
    above_ma60: bool | None
    ma_bullish: bool | None
    momentum_ok: bool | None
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


def market_diagnostics(session: Session, symbols: list[str]) -> list[MarketSymbolDiagnostic]:
    diagnostics = []
    for symbol in symbols:
        joined = _latest_joined(session, symbol)
        if joined is None:
            diagnostics.append(
                MarketSymbolDiagnostic(
                    symbol=symbol,
                    ready=False,
                    passed=False,
                    as_of=None,
                    close=None,
                    ma20=None,
                    ma60=None,
                    macd_dif=None,
                    above_ma60=None,
                    ma_bullish=None,
                    momentum_ok=None,
                    reason=f"{symbol} market data or indicators missing",
                )
            )
            continue
        kline, indicator = joined
        if indicator.ma60 is None or indicator.ma20 is None or indicator.macd_dif is None:
            diagnostics.append(
                MarketSymbolDiagnostic(
                    symbol=symbol,
                    ready=False,
                    passed=False,
                    as_of=kline.ts.date(),
                    close=kline.close,
                    ma20=indicator.ma20,
                    ma60=indicator.ma60,
                    macd_dif=indicator.macd_dif,
                    above_ma60=None,
                    ma_bullish=None,
                    momentum_ok=None,
                    reason=f"{symbol} market indicators insufficient",
                )
            )
            continue
        above_ma60 = kline.close > indicator.ma60
        ma_bullish = indicator.ma20 >= indicator.ma60
        momentum_ok = indicator.macd_dif >= 0 or kline.close >= indicator.ma20
        passed = above_ma60 and ma_bullish and momentum_ok
        diagnostics.append(
            MarketSymbolDiagnostic(
                symbol=symbol,
                ready=True,
                passed=passed,
                as_of=kline.ts.date(),
                close=kline.close,
                ma20=indicator.ma20,
                ma60=indicator.ma60,
                macd_dif=indicator.macd_dif,
                above_ma60=above_ma60,
                ma_bullish=ma_bullish,
                momentum_ok=momentum_ok,
                reason=(
                    f"{symbol}: close {'>' if above_ma60 else '<='} MA60, "
                    f"MA20 {'>=' if ma_bullish else '<'} MA60, "
                    f"MACD {'ok' if momentum_ok else 'weak'}"
                ),
            )
        )
    return diagnostics


def evaluate_market(session: Session, symbols: list[str]) -> MarketEvaluation:
    diagnostics = market_diagnostics(session, symbols)
    ready = [item for item in diagnostics if item.ready]
    latest_dates = [item.as_of for item in diagnostics if item.as_of is not None]
    as_of = max(latest_dates) if latest_dates else date.today()
    reasons = [item.reason for item in diagnostics]
    if len(ready) != len(symbols):
        return MarketEvaluation(as_of, "RISK_OFF", "; ".join(reasons))

    strong_count = sum(1 for item in ready if item.passed)
    if strong_count == len(ready):
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
