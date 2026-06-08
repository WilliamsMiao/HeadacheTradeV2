from datetime import datetime, timedelta

from app.models import Indicator, KLine
from app.services.structures import detect_latest_structures, persist_structure_detections


def test_structure_events_are_deduplicated(session):
    symbol = "AAPL"
    start = datetime(2025, 1, 1)
    for i in range(45):
        close = 100 - min(i, 35) * 0.5 + max(0, i - 38) * 1.2
        low = close - 1
        high = close + 1
        session.add(KLine(symbol=symbol, timeframe="1d", ts=start + timedelta(days=i), open=close, high=high, low=low, close=close, volume=1_000_000))
        session.add(
            Indicator(
                symbol=symbol,
                timeframe="1d",
                ts=start + timedelta(days=i),
                ma20=close - 0.5,
                ma60=close - 2,
                macd_dif=-2 + i * 0.05,
                macd_dea=-2,
                macd_hist=-1 + i * 0.04,
                atr=2,
                volume_ma20=900_000,
            )
        )
    session.commit()
    detections = detect_latest_structures(session, symbol, "1d")
    first = persist_structure_detections(session, detections, "RISK_ON", "UPTREND")
    second = persist_structure_detections(session, detections, "RISK_ON", "UPTREND")
    assert len(second) == len(first)

