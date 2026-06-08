from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Indicator, KLine


@dataclass(frozen=True)
class IndicatorRow:
    ma20: float | None
    ma60: float | None
    macd_dif: float | None
    macd_dea: float | None
    macd_hist: float | None
    atr: float | None
    volume_ma20: float | None


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


def calculate_indicator_rows(klines: list[KLine]) -> list[IndicatorRow]:
    ordered = sorted(klines, key=lambda item: item.ts)
    closes = [item.close for item in ordered]
    highs = [item.high for item in ordered]
    lows = [item.low for item in ordered]
    volumes = [item.volume for item in ordered]
    ma20 = _rolling_average(closes, 20)
    ma60 = _rolling_average(closes, 60)
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
    return [
        IndicatorRow(
            ma20=ma20[index],
            ma60=ma60[index],
            macd_dif=dif[index],
            macd_dea=dea[index],
            macd_hist=hist[index],
            atr=atr[index],
            volume_ma20=volume_ma20[index],
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
        indicator.ma20 = row.ma20
        indicator.ma60 = row.ma60
        indicator.macd_dif = row.macd_dif
        indicator.macd_dea = row.macd_dea
        indicator.macd_hist = row.macd_hist
        indicator.atr = row.atr
        indicator.volume_ma20 = row.volume_ma20
        count += 1
    session.commit()
    return count

