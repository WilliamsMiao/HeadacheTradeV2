from dataclasses import dataclass
from math import sqrt

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Indicator, KLine


@dataclass(frozen=True)
class IndicatorRow:
    ma5: float | None
    ma10: float | None
    ma20: float | None
    ma60: float | None
    ema5: float | None
    ema10: float | None
    ema20: float | None
    ema60: float | None
    macd_dif: float | None
    macd_dea: float | None
    macd_hist: float | None
    atr: float | None
    volume_ma20: float | None
    boll_mid: float | None
    boll_upper: float | None
    boll_lower: float | None
    rsi6: float | None
    rsi14: float | None
    kdj_k: float | None
    kdj_d: float | None
    kdj_j: float | None
    turnover: float | None
    turnover_ma20: float | None
    volume_ratio: float | None
    change_pct: float | None
    amplitude_pct: float | None


def _ema(values: list[float], span: int) -> list[float | None]:
    if not values:
        return []
    alpha = 2 / (span + 1)
    output: list[float | None] = []
    current: float | None = None
    for value in values:
        current = value if current is None else alpha * value + (1 - alpha) * current
        output.append(current)
    return output


def _rolling_average(values: list[float], window: int) -> list[float | None]:
    result: list[float | None] = []
    total = 0.0
    for index, value in enumerate(values):
        total += value
        if index >= window:
            total -= values[index - window]
        result.append(total / window if index + 1 >= window else None)
    return result


def _rolling_std(values: list[float], window: int) -> list[float | None]:
    result: list[float | None] = []
    for index in range(len(values)):
        if index + 1 < window:
            result.append(None)
            continue
        window_values = values[index + 1 - window : index + 1]
        mean = sum(window_values) / window
        result.append(sqrt(sum((value - mean) ** 2 for value in window_values) / window))
    return result


def _rsi(values: list[float], period: int) -> list[float | None]:
    if not values:
        return []
    output: list[float | None] = [None]
    gains: list[float] = []
    losses: list[float] = []
    for index in range(1, len(values)):
        change = values[index] - values[index - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
        if index < period:
            output.append(None)
            continue
        if index == period:
            avg_gain = sum(gains[-period:]) / period
            avg_loss = sum(losses[-period:]) / period
        else:
            avg_gain = ((avg_gain * (period - 1)) + gains[-1]) / period
            avg_loss = ((avg_loss * (period - 1)) + losses[-1]) / period
        if avg_loss == 0:
            output.append(100.0)
        else:
            rs = avg_gain / avg_loss
            output.append(100 - (100 / (1 + rs)))
    return output


def _kdj(highs: list[float], lows: list[float], closes: list[float], period: int = 9):
    k_values: list[float | None] = []
    d_values: list[float | None] = []
    j_values: list[float | None] = []
    k = 50.0
    d = 50.0
    for index, close in enumerate(closes):
        if index + 1 < period:
            k_values.append(None)
            d_values.append(None)
            j_values.append(None)
            continue
        highest = max(highs[index + 1 - period : index + 1])
        lowest = min(lows[index + 1 - period : index + 1])
        rsv = 50.0 if highest == lowest else (close - lowest) / (highest - lowest) * 100
        k = (2 * k + rsv) / 3
        d = (2 * d + k) / 3
        k_values.append(k)
        d_values.append(d)
        j_values.append(3 * k - 2 * d)
    return k_values, d_values, j_values


def calculate_indicator_rows(klines: list[KLine]) -> list[IndicatorRow]:
    ordered = sorted(klines, key=lambda item: item.ts)
    closes = [item.close for item in ordered]
    highs = [item.high for item in ordered]
    lows = [item.low for item in ordered]
    volumes = [item.volume for item in ordered]
    turnovers = [
        item.turnover if item.turnover is not None and item.turnover > 0 else item.close * item.volume
        for item in ordered
    ]
    ma5 = _rolling_average(closes, 5)
    ma10 = _rolling_average(closes, 10)
    ma20 = _rolling_average(closes, 20)
    ma60 = _rolling_average(closes, 60)
    ema5 = _ema(closes, 5)
    ema10 = _ema(closes, 10)
    ema20 = _ema(closes, 20)
    ema60 = _ema(closes, 60)
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    dif = [(a - b) if a is not None and b is not None else None for a, b in zip(ema12, ema26, strict=True)]
    dea_raw = _ema([value if value is not None else 0 for value in dif], 9)
    dea = [value if index >= 25 else None for index, value in enumerate(dea_raw)]
    hist = [(d - e) * 2 if d is not None and e is not None else None for d, e in zip(dif, dea, strict=True)]

    true_ranges: list[float] = []
    for index, high in enumerate(highs):
        if index == 0:
            true_ranges.append(high - lows[index])
        else:
            previous_close = closes[index - 1]
            true_ranges.append(max(high - lows[index], abs(high - previous_close), abs(lows[index] - previous_close)))
    atr = _rolling_average(true_ranges, 14)
    volume_ma20 = _rolling_average(volumes, 20)
    turnover_ma20 = _rolling_average(turnovers, 20)
    std20 = _rolling_std(closes, 20)
    boll_upper = [
        mid + 2 * std if mid is not None and std is not None else None
        for mid, std in zip(ma20, std20, strict=True)
    ]
    boll_lower = [
        mid - 2 * std if mid is not None and std is not None else None
        for mid, std in zip(ma20, std20, strict=True)
    ]
    rsi6 = _rsi(closes, 6)
    rsi14 = _rsi(closes, 14)
    kdj_k, kdj_d, kdj_j = _kdj(highs, lows, closes)
    change_pct = [
        None if index == 0 or closes[index - 1] == 0 else (close / closes[index - 1] - 1)
        for index, close in enumerate(closes)
    ]
    amplitude_pct = [
        None if index == 0 or closes[index - 1] == 0 else (highs[index] - lows[index]) / closes[index - 1]
        for index in range(len(closes))
    ]
    return [
        IndicatorRow(
            ma5=ma5[index],
            ma10=ma10[index],
            ma20=ma20[index],
            ma60=ma60[index],
            ema5=ema5[index],
            ema10=ema10[index],
            ema20=ema20[index],
            ema60=ema60[index],
            macd_dif=dif[index],
            macd_dea=dea[index],
            macd_hist=hist[index],
            atr=atr[index],
            volume_ma20=volume_ma20[index],
            boll_mid=ma20[index],
            boll_upper=boll_upper[index],
            boll_lower=boll_lower[index],
            rsi6=rsi6[index],
            rsi14=rsi14[index],
            kdj_k=kdj_k[index],
            kdj_d=kdj_d[index],
            kdj_j=kdj_j[index],
            turnover=turnovers[index],
            turnover_ma20=turnover_ma20[index],
            volume_ratio=(
                volumes[index] / volume_ma20[index]
                if volume_ma20[index] not in (None, 0)
                else None
            ),
            change_pct=change_pct[index],
            amplitude_pct=amplitude_pct[index],
        )
        for index in range(len(ordered))
    ]


def compute_indicators_for_symbol(session: Session, symbol: str, timeframe: str) -> int:
    klines = list(
        session.scalars(
            select(KLine)
            .where(KLine.symbol == symbol, KLine.timeframe == timeframe, KLine.data_ok.is_(True))
            .order_by(KLine.ts)
        )
    )
    rows = calculate_indicator_rows(klines)
    count = 0
    for kline, row in zip(klines, rows, strict=True):
        indicator = session.scalar(
            select(Indicator).where(
                Indicator.symbol == symbol,
                Indicator.timeframe == timeframe,
                Indicator.ts == kline.ts,
            )
        )
        if indicator is None:
            indicator = Indicator(symbol=symbol, timeframe=timeframe, ts=kline.ts)
            session.add(indicator)
        for field in IndicatorRow.__dataclass_fields__:
            setattr(indicator, field, getattr(row, field))
        count += 1
    session.commit()
    return count
