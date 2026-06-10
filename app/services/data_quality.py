from app.domain import Bar


def validate_bar(bar: Bar) -> tuple[bool, str]:
    if bar.open <= 0 or bar.high <= 0 or bar.low <= 0 or bar.close <= 0:
        return False, f"{bar.symbol} {bar.timeframe} has non-positive OHLC at {bar.ts}"
    if bar.high + 1e-8 < max(bar.open, bar.close, bar.low):
        return False, f"{bar.symbol} {bar.timeframe} high is inconsistent at {bar.ts}"
    if bar.low - 1e-8 > min(bar.open, bar.close, bar.high):
        return False, f"{bar.symbol} {bar.timeframe} low is inconsistent at {bar.ts}"
    if bar.volume <= 0:
        return False, f"{bar.symbol} {bar.timeframe} has zero volume at {bar.ts}"
    return True, "data quality passed"


def validate_bars(bars: list[Bar]) -> tuple[bool, str]:
    if not bars:
        return False, "no bars returned from data source"
    previous_ts = None
    for bar in sorted(bars, key=lambda item: item.ts):
        ok, reason = validate_bar(bar)
        if not ok:
            return False, reason
        if previous_ts and bar.ts <= previous_ts:
            return False, f"{bar.symbol} {bar.timeframe} timestamps are not strictly increasing"
        previous_ts = bar.ts
    return True, "data quality passed"
