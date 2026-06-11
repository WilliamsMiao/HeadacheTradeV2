from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import DAILY
from app.models import DailyState, Indicator, KLine


@dataclass(frozen=True)
class DailyStateEvaluation:
    symbol: str
    as_of: object
    state: str
    reason: str


def evaluate_daily_state(session: Session, symbol: str) -> DailyStateEvaluation:
    rows = list(
        session.execute(
            select(KLine, Indicator)
            .join(
                Indicator,
                (Indicator.symbol == KLine.symbol)
                & (Indicator.timeframe == KLine.timeframe)
                & (Indicator.ts == KLine.ts),
            )
            .where(
                KLine.symbol == symbol,
                KLine.timeframe == DAILY,
                KLine.data_ok.is_(True),
            )
            .order_by(KLine.ts.desc())
            .limit(6)
        )
    )
    if len(rows) < 6:
        return DailyStateEvaluation(symbol, None, "UNKNOWN", "日线行情或指标历史不足")
    current_bar, current = rows[0]
    _, prior = rows[-1]
    required = (current.ma20, current.ma60, current.macd_dif, prior.ma20)
    if any(value is None for value in required):
        return DailyStateEvaluation(symbol, current_bar.ts.date(), "UNKNOWN", "MA20、MA60 或 MACD 尚未形成")

    ma20_slope = current.ma20 - prior.ma20
    distance = abs(current_bar.close - current.ma20) / current.ma20 if current.ma20 else 1
    if (
        current_bar.close > current.ma20 > current.ma60
        and ma20_slope > 0
        and current.macd_dif > 0
        and distance <= 0.18
    ):
        state = "DAILY_STRONG_BULL"
        reason = "价格站上 MA20，MA20 高于 MA60 且持续上行，MACD 位于零轴上方"
    elif (
        current_bar.close >= current.ma20 * 0.97
        and current.ma20 >= current.ma60 * 0.98
        and ma20_slope >= -current.ma20 * 0.002
        and current.macd_dif >= -current_bar.close * 0.01
    ):
        state = "DAILY_WEAK_BULL"
        reason = "价格守在 MA20 附近，均线结构未转空，MACD 未进入深度弱势"
    elif (
        abs(current_bar.close - current.ma20) / current.ma20 <= 0.05
        and abs(ma20_slope) / current.ma20 <= 0.01
    ):
        state = "DAILY_RANGE"
        reason = "价格围绕 MA20 与 BOLL 中轨反复，MA20 斜率接近平坦"
    elif (
        current_bar.close < current.ma20 < current.ma60
        and ma20_slope < 0
        and (current.boll_mid is None or current_bar.close < current.boll_mid)
    ):
        state = "DAILY_STRONG_BEAR"
        reason = "价格低于 MA20，MA20 低于 MA60 且继续下行，反弹未收复中轨"
    else:
        state = "DAILY_WEAK_BEAR"
        reason = "价格跌破 MA20 或 MA20 已转弱，但尚未形成完整空头排列"
    return DailyStateEvaluation(symbol, current_bar.ts.date(), state, reason)


def persist_daily_state(session: Session, evaluation: DailyStateEvaluation) -> DailyState:
    if evaluation.as_of is None:
        raise ValueError("不能持久化没有日期的日线状态")
    record = session.scalar(
        select(DailyState).where(
            DailyState.symbol == evaluation.symbol,
            DailyState.as_of == evaluation.as_of,
        )
    )
    if record is None:
        record = DailyState(symbol=evaluation.symbol, as_of=evaluation.as_of)
        session.add(record)
    record.state = evaluation.state
    record.reason = evaluation.reason
    session.commit()
    return record
