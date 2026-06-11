from datetime import date, datetime

from sqlalchemy import func, select

from app.config import get_settings
from app.models import BacktestTrade, KLine, TradeSignal, TradingState, WatchlistItem
from app.services import backtest
from app.services.backtest import _available_at, _calculate_stats, _precompute_indicators, run_backtest
from app.services.market import MarketEvaluation
from app.services.structures import StructureDetection
from app.services.trend import TrendEvaluation


def _bar(symbol: str, timeframe: str, ts: datetime, close: float, low: float | None = None) -> KLine:
    return KLine(
        symbol=symbol,
        timeframe=timeframe,
        ts=ts,
        open=close,
        high=close + 1,
        low=low if low is not None else close - 1,
        close=close,
        volume=1_000_000,
    )


def test_time_step_backtest_hides_future_and_records_complete_trade(session, monkeypatch):
    structure_ts = datetime(2026, 1, 2, 9)
    entry_ts = datetime(2026, 1, 2, 10, 15)
    exit_ts = datetime(2026, 1, 2, 10, 30)
    session.add(WatchlistItem(symbol="AAPL", name="Apple", active=True))
    session.add_all(
        [
            _bar("AAPL", "1d", datetime(2026, 1, 1, 9), 100),
            _bar("AAPL", "60m", structure_ts, 100),
            _bar("AAPL", "15m", entry_ts, 102),
            _bar("AAPL", "15m", exit_ts, 94, low=94),
        ]
    )
    session.commit()

    def fake_market(replay, symbols):
        return MarketEvaluation(date(2026, 1, 2), "RISK_ON", "test market")

    def fake_trend(replay, symbol):
        return TrendEvaluation(symbol, "UPTREND", "test trend")

    def fake_structures(replay, symbol, timeframe):
        existing = replay.scalar(select(KLine).where(KLine.symbol == symbol, KLine.ts == structure_ts))
        if existing is None:
            return []
        return [
            StructureDetection(
                symbol=symbol,
                timeframe="60m",
                event_type="BOTTOM_STRUCTURE",
                event_ts=structure_ts,
                price=100,
                pivot_low=95,
                invalidation_level=95,
                trigger_level=101,
                reason="test bottom structure",
            )
        ]

    def fake_advance(replay, symbol, market_state, stock_trend, *, as_of_date=None):
        state = replay.scalar(select(TradingState).where(TradingState.symbol == symbol))
        if state is None:
            state = TradingState(symbol=symbol, state="WAIT_15M_TRIGGER")
            replay.add(state)
            replay.flush()
        current = replay.scalar(
            select(KLine)
            .where(KLine.symbol == symbol, KLine.timeframe == "15m")
            .order_by(KLine.ts.desc())
            .limit(1)
        )
        structure = replay.scalar(
            select(backtest.StructureEvent)
            .where(backtest.StructureEvent.symbol == symbol, backtest.StructureEvent.event_type == "BOTTOM_STRUCTURE")
            .limit(1)
        )
        pending = replay.scalar(
            select(TradeSignal).where(
                TradeSignal.symbol == symbol,
                TradeSignal.signal_type == "ENTRY",
                TradeSignal.status == "PENDING",
            )
        )
        if current and current.ts == entry_ts and structure and pending is None:
            replay.add(
                TradeSignal(
                    symbol=symbol,
                    signal_type="ENTRY",
                    script="SCRIPT_A_BOTTOM_TREND_RESUME",
                    action="入场候选",
                    entry_price=102,
                    stop_price=95,
                    shares=100,
                    risk_amount=700,
                    source_structure_id=structure.id,
                    trigger_timeframe="15m",
                    trigger_ts=entry_ts,
                    trigger_level=101,
                    reason="test 15m trigger",
                )
            )
            state.state = "ENTRY_CANDIDATE"
        replay.commit()
        return state

    monkeypatch.setattr(backtest, "evaluate_market", fake_market)
    monkeypatch.setattr(backtest, "evaluate_stock_trend", fake_trend)
    monkeypatch.setattr(backtest, "detect_latest_structures", fake_structures)
    monkeypatch.setattr(backtest, "advance_state_machine", fake_advance)

    observed: list[tuple[datetime, datetime | None]] = []

    def observe(current_ts, replay):
        max_visible = replay.scalar(select(func.max(KLine.ts)))
        observed.append((current_ts, max_visible))
        assert max_visible is None or max_visible <= current_ts

    result = run_backtest(
        session,
        get_settings(),
        symbols=["AAPL"],
        step_observer=observe,
    )

    trade = session.scalar(select(BacktestTrade).where(BacktestTrade.run_id == result["run_id"]))
    assert observed
    assert trade is not None
    assert trade.source_structure_id is not None
    assert trade.structure_type == "BOTTOM_STRUCTURE"
    assert trade.structure_ts == structure_ts
    assert trade.trigger_timeframe == "15m"
    assert trade.entry_ts == entry_ts
    assert trade.exit_ts == exit_ts
    assert trade.exit_reason == "HARD_STOP"
    assert trade.final_r == -1
    assert result["trade_count"] == 1
    assert result["trade_ids"] == [trade.id]
    assert result["market_state_group_performance"]["RISK_ON"] == -1
    assert session.scalar(select(TradeSignal)) is None


def test_backtest_statistics_use_r_multiples_and_robust_median():
    trades = [
        _trade("AAPL", datetime(2025, 1, 2), -1, "RISK_ON", 3),
        _trade("MSFT", datetime(2025, 2, 2), 1, "RISK_ON", 5),
        _trade("NVDA", datetime(2026, 2, 2), 8, "NEUTRAL_POSITIVE", 2),
    ]
    bars = [
        _bar(trade.symbol, "15m", trade.entry_ts, trade.entry_price)
        for trade in trades
        for _ in range(5)
    ]

    stats = _calculate_stats(trades, bars, [trade.symbol for trade in trades])

    assert stats["trade_count"] == 3
    assert stats["avg_r"] == 8 / 3
    assert stats["median_r"] == 1
    assert stats["max_drawdown"] == -1
    assert stats["max_consecutive_losses"] == 1
    assert stats["yearly_performance"] == {"2025": 0.0, "2026": 8.0}
    assert stats["market_state_group_performance"]["RISK_ON"] == 0


def test_precomputed_indicator_rows_do_not_change_when_future_bar_is_added():
    start = datetime(2026, 1, 2, 9, 30)
    history = [
        _bar("AAPL", "15m", start.replace(minute=30 + index * 15), 100 + index)
        for index in range(2)
    ]
    first = _precompute_indicators(history)
    extended = _precompute_indicators(
        [*history, _bar("AAPL", "15m", datetime(2026, 1, 2, 10), 1000)]
    )

    key = ("AAPL", "15m", history[1].ts)
    assert first[key] == extended[key]


def test_bar_availability_waits_until_timeframe_is_complete():
    ts = datetime(2026, 1, 2, 10)
    assert _available_at(_bar("AAPL", "15m", ts, 100)) == datetime(2026, 1, 2, 10, 15)
    assert _available_at(_bar("AAPL", "60m", ts, 100)) == datetime(2026, 1, 2, 11)
    assert _available_at(_bar("AAPL", "1d", ts, 100)) == datetime(2026, 1, 3, 10)


def _trade(
    symbol: str,
    exit_ts: datetime,
    final_r: float,
    market_state: str,
    holding_bars: int,
) -> BacktestTrade:
    return BacktestTrade(
        run_id="test",
        symbol=symbol,
        script="SCRIPT_A_BOTTOM_TREND_RESUME",
        source_structure_id=1,
        structure_type="BOTTOM_STRUCTURE",
        structure_ts=exit_ts,
        trigger_timeframe="15m",
        trigger_reason="trigger",
        entry_ts=exit_ts,
        entry_price=100,
        stop_price=95,
        shares=100,
        risk_amount=500,
        exit_ts=exit_ts,
        exit_price=100 + final_r * 5,
        exit_reason="TEST",
        max_r=max(0, final_r),
        min_r=min(0, final_r),
        final_r=final_r,
        holding_bars=holding_bars,
        market_state_at_entry=market_state,
        stock_trend_at_entry="UPTREND",
    )
