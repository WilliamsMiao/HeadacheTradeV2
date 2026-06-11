from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.domain import SUPPORTED_TIMEFRAMES, TIMEFRAME_LABELS, TRADEABLE_MARKETS
from app.models import (
    Indicator,
    KLine,
    MarketState,
    Position,
    StockTrend,
    StructureEvent,
    TradeSignal,
    TradingState,
    WatchlistItem,
)
from app.presentation import format_reason, label_for
from app.services.market import market_diagnostics
from app.services.pipeline import symbol_data_status


def workbench_watchlist(session: Session) -> list[dict[str, Any]]:
    items = list(
        session.scalars(
            select(WatchlistItem).where(WatchlistItem.active.is_(True)).order_by(WatchlistItem.symbol)
        )
    )
    rows: list[dict[str, Any]] = []
    for item in items:
        trend = session.scalar(
            select(StockTrend)
            .where(StockTrend.symbol == item.symbol)
            .order_by(StockTrend.as_of.desc())
            .limit(1)
        )
        state = session.scalar(select(TradingState).where(TradingState.symbol == item.symbol))
        structure = session.scalar(
            select(StructureEvent)
            .where(StructureEvent.symbol == item.symbol)
            .order_by(StructureEvent.event_ts.desc())
            .limit(1)
        )
        signal = session.scalar(
            select(TradeSignal)
            .where(TradeSignal.symbol == item.symbol, TradeSignal.status == "PENDING")
            .order_by(TradeSignal.created_at.desc())
            .limit(1)
        )
        position = session.scalar(
            select(Position).where(Position.symbol == item.symbol, Position.status == "OPEN")
        )
        data_ok, data_reason = symbol_data_status(session, item.symbol)
        rows.append(
            {
                "symbol": item.symbol,
                "name": item.name,
                "trend": trend.trend if trend else "UNKNOWN",
                "trend_label": label_for(trend.trend if trend else "UNKNOWN"),
                "state": state.state if state else "IDLE",
                "state_label": label_for(state.state if state else "IDLE"),
                "structure": structure.event_type if structure else "",
                "structure_label": label_for(structure.event_type) if structure else "暂无结构",
                "pending": bool(signal),
                "position": bool(position),
                "cooldown": state.cooldown_until.isoformat() if state and state.cooldown_until else "",
                "data_ok": data_ok,
                "data_reason": format_reason(data_reason),
            }
        )
    return rows


def frames_payload(session: Session, symbol: str, limit: int = 120) -> dict[str, Any]:
    symbol = symbol.upper()
    position = session.scalar(
        select(Position).where(Position.symbol == symbol, Position.status == "OPEN")
    )
    frame_payloads: dict[str, Any] = {}
    for timeframe in SUPPORTED_TIMEFRAMES:
        bars_desc = list(
            session.scalars(
                select(KLine)
                .where(KLine.symbol == symbol, KLine.timeframe == timeframe)
                .order_by(KLine.ts.desc())
                .limit(limit)
            )
        )
        bars = list(reversed(bars_desc))
        indicators = {
            row.ts: row
            for row in session.scalars(
                select(Indicator).where(
                    Indicator.symbol == symbol,
                    Indicator.timeframe == timeframe,
                    Indicator.ts.in_([bar.ts for bar in bars]),
                )
            )
        } if bars else {}
        events = list(
            session.scalars(
                select(StructureEvent)
                .where(
                    StructureEvent.symbol == symbol,
                    StructureEvent.timeframe == timeframe,
                    StructureEvent.event_ts >= bars[0].ts,
                    StructureEvent.event_ts <= bars[-1].ts,
                )
                .order_by(StructureEvent.event_ts.desc())
                .limit(40)
            )
        ) if bars else []
        signals = _signal_markers(
            session,
            symbol,
            timeframe,
            bars[0].ts if bars else None,
            bars[-1].ts if bars else None,
        )
        frame_payloads[timeframe] = {
            "timeframe": timeframe,
            "label": TIMEFRAME_LABELS[timeframe],
            "available": bool(bars),
            "data_ok": bool(bars) and all(bar.data_ok for bar in bars),
            "bars": [_bar_payload(bar, indicators.get(bar.ts)) for bar in bars],
            "events": [_event_marker(event) for event in reversed(events)],
            "signals": signals,
            "levels": _position_levels(position),
        }
    return {"symbol": symbol, "frames": frame_payloads}


def state_payload(session: Session, settings: Settings, symbol: str) -> dict[str, Any]:
    symbol = symbol.upper()
    item = _require_symbol(session, symbol)
    market = session.scalar(select(MarketState).order_by(MarketState.updated_at.desc()).limit(1))
    trend = session.scalar(
        select(StockTrend).where(StockTrend.symbol == symbol).order_by(StockTrend.as_of.desc()).limit(1)
    )
    state = session.scalar(select(TradingState).where(TradingState.symbol == symbol))
    position = session.scalar(
        select(Position).where(Position.symbol == symbol, Position.status == "OPEN")
    )
    pending = session.scalar(
        select(TradeSignal)
        .where(TradeSignal.symbol == symbol, TradeSignal.status == "PENDING")
        .order_by(TradeSignal.created_at.desc())
        .limit(1)
    )
    data_ok, data_reason = symbol_data_status(session, symbol)
    market_checks = [
        {
            "symbol": check.symbol,
            "ready": check.ready,
            "passed": check.passed,
            "as_of": check.as_of.isoformat() if check.as_of else None,
            "close": check.close,
            "ma20": check.ma20,
            "ma60": check.ma60,
            "macd_dif": check.macd_dif,
            "above_ma60": check.above_ma60,
            "ma_bullish": check.ma_bullish,
            "momentum_ok": check.momentum_ok,
            "reason": format_reason(check.reason),
        }
        for check in market_diagnostics(session, settings.market_symbols)
    ]
    return {
        "symbol": symbol,
        "name": item.name,
        "market": _named_state(market.state if market else "", market.reason if market else ""),
        "market_checks": market_checks,
        "trend": _named_state(trend.trend if trend else "UNKNOWN", trend.reason if trend else ""),
        "trading_state": _named_state(
            state.state if state else "IDLE",
            state.last_reason if state else "等待状态机初始化",
        ),
        "next_wait": format_reason(state.next_wait if state else "等待状态机初始化"),
        "cooldown_until": state.cooldown_until.isoformat() if state and state.cooldown_until else None,
        "data": {"ok": data_ok, "reason": format_reason(data_reason)},
        "position": _position_payload(position),
        "pending_signal": _signal_payload(pending) if pending else None,
        "playbooks": _playbook_status(market, trend, state, pending, position, data_ok),
    }


def events_payload(session: Session, symbol: str) -> dict[str, Any]:
    _require_symbol(session, symbol.upper())
    events = list(
        session.scalars(
            select(StructureEvent)
            .where(StructureEvent.symbol == symbol.upper())
            .order_by(StructureEvent.event_ts.desc())
            .limit(100)
        )
    )
    return {"symbol": symbol.upper(), "events": [_event_payload(event) for event in events]}


def signals_payload(session: Session, symbol: str) -> dict[str, Any]:
    _require_symbol(session, symbol.upper())
    signals = list(
        session.scalars(
            select(TradeSignal)
            .where(TradeSignal.symbol == symbol.upper())
            .order_by(TradeSignal.created_at.desc())
            .limit(100)
        )
    )
    return {"symbol": symbol.upper(), "signals": [_signal_payload(signal) for signal in signals]}


def debug_payload(session: Session, settings: Settings, symbol: str) -> dict[str, Any]:
    state = state_payload(session, settings, symbol)
    frames = frames_payload(session, symbol)
    return {
        "symbol": symbol.upper(),
        "generated_at": datetime.now(UTC).isoformat(),
        "source": "server_read_model",
        "state": state,
        "frame_summary": {
            timeframe: {
                "available": frame["available"],
                "data_ok": frame["data_ok"],
                "bar_count": len(frame["bars"]),
                "event_count": len(frame["events"]),
                "signal_count": len(frame["signals"]),
            }
            for timeframe, frame in frames["frames"].items()
        },
    }


def _require_symbol(session: Session, symbol: str) -> WatchlistItem:
    item = session.scalar(select(WatchlistItem).where(WatchlistItem.symbol == symbol))
    if item is None:
        raise LookupError("symbol not found")
    return item


def _bar_payload(bar: KLine, indicator: Indicator | None) -> dict[str, Any]:
    return {
        "ts": bar.ts.isoformat(),
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
        "data_ok": bar.data_ok,
        "ma20": indicator.ma20 if indicator else None,
        "ma60": indicator.ma60 if indicator else None,
        "macd_dif": indicator.macd_dif if indicator else None,
        "macd_dea": indicator.macd_dea if indicator else None,
        "macd_hist": indicator.macd_hist if indicator else None,
    }


def _event_marker(event: StructureEvent) -> dict[str, Any]:
    return {
        "ts": event.event_ts.isoformat(),
        "price": event.price,
        "kind": event.event_type,
        "label": label_for(event.event_type),
        "invalidated": event.invalidated,
    }


def _event_payload(event: StructureEvent) -> dict[str, Any]:
    return {
        **_event_marker(event),
        "id": event.id,
        "timeframe": event.timeframe,
        "timeframe_label": label_for(event.timeframe),
        "reason": format_reason(event.reason),
        "pivot_low": event.pivot_low,
        "pivot_high": event.pivot_high,
        "confirm_level": event.confirm_level,
        "invalidation_level": event.invalidation_level,
        "trigger_level": event.trigger_level,
        "expires_at": event.expires_at.isoformat() if event.expires_at else None,
    }


def _signal_markers(
    session: Session,
    symbol: str,
    timeframe: str,
    start: datetime | None,
    end: datetime | None,
) -> list[dict[str, Any]]:
    if start is None or end is None:
        return []
    rows = list(
        session.scalars(
            select(TradeSignal)
            .where(TradeSignal.symbol == symbol)
            .order_by(TradeSignal.created_at.desc())
            .limit(100)
        )
    )
    markers = []
    for signal in reversed(rows):
        marker_timeframe = signal.trigger_timeframe or "1d"
        marker_ts = signal.trigger_ts or signal.created_at
        if marker_timeframe != timeframe or marker_ts < start or marker_ts > end:
            continue
        marker_kind, marker_label = _chart_signal_identity(signal)
        markers.append(
            {
                "ts": marker_ts.isoformat(),
                "price": signal.entry_price or signal.stop_price,
                "kind": marker_kind,
                "label": marker_label,
                "status": signal.status,
                "source_type": signal.signal_type,
            }
        )
    return markers


def _chart_signal_identity(signal: TradeSignal) -> tuple[str, str]:
    if signal.signal_type == "ENTRY":
        return "BUY", "买入"
    if signal.signal_type == "REDUCE":
        return "REDUCE", "减仓"
    reason = (signal.cancel_reason or signal.reason or "").lower()
    if "hard stop" in reason or "硬止损" in reason:
        return "STOP", "止损"
    if "trailing stop" in reason or "滑动止盈" in reason:
        return "TRAIL", "滑动止盈"
    return "SELL", "卖出"


def _signal_payload(signal: TradeSignal) -> dict[str, Any]:
    return {
        "id": signal.id,
        "type": signal.signal_type,
        "type_label": label_for(signal.signal_type),
        "script": signal.script,
        "script_label": label_for(signal.script),
        "status": signal.status,
        "status_label": label_for(signal.status),
        "action": signal.action,
        "created_at": signal.created_at.isoformat(),
        "entry_price": signal.entry_price,
        "stop_price": signal.stop_price,
        "shares": signal.shares,
        "risk_amount": signal.risk_amount,
        "risk_r": signal.risk_r,
        "source_structure_id": signal.source_structure_id,
        "trigger_timeframe": signal.trigger_timeframe,
        "trigger_timeframe_label": label_for(signal.trigger_timeframe),
        "trigger_ts": signal.trigger_ts.isoformat() if signal.trigger_ts else None,
        "trigger_level": signal.trigger_level,
        "reason": format_reason(signal.cancel_reason or signal.reason),
    }


def _position_payload(position: Position | None) -> dict[str, Any] | None:
    if not position:
        return None
    return {
        "shares": position.shares,
        "entry_price": position.entry_price,
        "stop_price": position.stop_price,
        "trailing_stop": position.trailing_stop,
        "risk_amount": position.risk_amount,
        "current_r": position.current_r,
    }


def _position_levels(position: Position | None) -> list[dict[str, Any]]:
    if not position:
        return []
    unit_r = max(position.entry_price - position.stop_price, 0)
    levels = [
        {"kind": "entry", "label": "持仓成本", "price": position.entry_price},
        {"kind": "stop", "label": "初始止损", "price": position.stop_price},
    ]
    if position.trailing_stop is not None:
        levels.append({"kind": "trail", "label": "滑动止盈", "price": position.trailing_stop})
    if unit_r > 0:
        levels.extend(
            {"kind": f"r{multiple}", "label": f"{multiple}R", "price": position.entry_price + unit_r * multiple}
            for multiple in (1, 2, 3)
        )
    return levels


def _named_state(value: str, reason: str) -> dict[str, str]:
    return {"value": value or "UNKNOWN", "label": label_for(value or "UNKNOWN"), "reason": format_reason(reason)}


def _playbook_status(
    market: MarketState | None,
    trend: StockTrend | None,
    state: TradingState | None,
    pending: TradeSignal | None,
    position: Position | None,
    data_ok: bool,
) -> list[dict[str, Any]]:
    common = [
        {"label": "核心周期数据正常", "passed": data_ok},
        {"label": "市场允许寻找新仓", "passed": bool(market and market.state in TRADEABLE_MARKETS)},
        {"label": "个股趋势通过过滤", "passed": bool(trend and trend.trend in {"UPTREND", "STRONG_UPTREND"})},
        {"label": "当前没有模拟持仓", "passed": position is None},
    ]
    return [
        {
            "name": label_for("SCRIPT_A_BOTTOM_TREND_RESUME"),
            "active": bool(pending and pending.script == "SCRIPT_A_BOTTOM_TREND_RESUME"),
            "conditions": common + [
                {
                    "label": "状态机已进入底结构确认或等待 15 分钟触发",
                    "passed": bool(state and state.state in {"BOTTOM_CONFIRMED", "WAIT_15M_TRIGGER", "WAIT_ENTRY_TRIGGER", "ENTRY_CANDIDATE"}),
                }
            ],
        },
        {
            "name": label_for("SCRIPT_B_TOP_INVALIDATION_CONTINUATION"),
            "active": bool(pending and pending.script == "SCRIPT_B_TOP_INVALIDATION_CONTINUATION"),
            "conditions": common + [
                {
                    "label": "状态机确认顶结构失效后的趋势延续",
                    "passed": bool(pending and pending.script == "SCRIPT_B_TOP_INVALIDATION_CONTINUATION"),
                }
            ],
        },
    ]
