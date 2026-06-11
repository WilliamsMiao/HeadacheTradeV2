from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import STRUCTURE_TIMEFRAME, TRIGGER_TIMEFRAME
from app.models import Indicator, KLine, StructureEvent
from app.strategy_config import ENTRY_TRIGGER_CONFIG, EntryTriggerConfig


@dataclass(frozen=True)
class EntryTriggerEvaluation:
    triggered: bool
    reason: str
    trigger_ts: datetime | None = None
    trigger_price: float | None = None
    trigger_level: float | None = None
    script_version: str = ENTRY_TRIGGER_CONFIG.script_version


def evaluate_15m_trend_resume(
    session: Session,
    symbol: str,
    structure: StructureEvent,
    config: EntryTriggerConfig = ENTRY_TRIGGER_CONFIG,
) -> EntryTriggerEvaluation:
    if structure.event_type != "BOTTOM_STRUCTURE" or structure.timeframe != STRUCTURE_TIMEFRAME:
        return EntryTriggerEvaluation(False, "缺少有效的 60 分钟底结构前置条件")
    if structure.invalidated or structure.became_failed:
        return EntryTriggerEvaluation(False, "60 分钟底结构已经失败或失效")

    latest_bar = session.scalar(
        select(KLine)
        .where(
            KLine.symbol == symbol,
            KLine.timeframe == TRIGGER_TIMEFRAME,
            KLine.data_ok.is_(True),
        )
        .order_by(KLine.ts.desc())
        .limit(1)
    )
    if latest_bar is None:
        return EntryTriggerEvaluation(False, "15 分钟行情缺失")
    if structure.expires_at is not None and latest_bar.ts > structure.expires_at:
        return EntryTriggerEvaluation(False, "60 分钟底结构已经过期")
    if latest_bar.ts <= structure.event_ts:
        return EntryTriggerEvaluation(False, "等待底结构确认后的新 15 分钟 K 线")

    history_limit = max(config.breakout_lookback_bars + 1, config.histogram_improvement_bars)
    bars = list(
        session.scalars(
            select(KLine)
            .where(
                KLine.symbol == symbol,
                KLine.timeframe == TRIGGER_TIMEFRAME,
                KLine.ts <= latest_bar.ts,
                KLine.data_ok.is_(True),
            )
            .order_by(KLine.ts.desc())
            .limit(history_limit)
        )
    )
    bars.reverse()
    if len(bars) < history_limit:
        return EntryTriggerEvaluation(False, "15 分钟历史不足，无法确认突破与动能改善")

    indicators = {
        item.ts: item
        for item in session.scalars(
            select(Indicator).where(
                Indicator.symbol == symbol,
                Indicator.timeframe == TRIGGER_TIMEFRAME,
                Indicator.ts.in_([bar.ts for bar in bars]),
            )
        )
    }
    ordered_indicators = [indicators.get(bar.ts) for bar in bars]
    if any(item is None for item in ordered_indicators):
        return EntryTriggerEvaluation(False, "15 分钟指标缺失")

    latest_indicator = ordered_indicators[-1]
    assert latest_indicator is not None
    required = (
        latest_indicator.ma20,
        latest_indicator.macd_dif,
        latest_indicator.macd_hist,
        latest_indicator.atr,
        latest_indicator.volume_ma20,
    )
    if any(value is None for value in required):
        return EntryTriggerEvaluation(False, "15 分钟指标历史不足")

    previous_bars = bars[-(config.breakout_lookback_bars + 1) : -1]
    breakout_level = max(bar.high for bar in previous_bars)
    histogram_window = ordered_indicators[-config.histogram_improvement_bars :]
    histogram_values = [item.macd_hist for item in histogram_window if item is not None]
    dif_previous = ordered_indicators[-2]
    assert dif_previous is not None

    checks: list[tuple[bool, str]] = [
        (latest_bar.close >= latest_indicator.ma20, "等待 15 分钟收盘价站回 MA20"),
        (latest_bar.close > breakout_level, f"等待突破最近 {config.breakout_lookback_bars} 根 15 分钟高点"),
        (
            len(histogram_values) == config.histogram_improvement_bars
            and all(
                current is not None and previous is not None and current > previous
                for previous, current in zip(histogram_values, histogram_values[1:])
            ),
            f"等待 MACD 柱连续 {config.histogram_improvement_bars} 根改善",
        ),
        (
            dif_previous.macd_dif is not None and latest_indicator.macd_dif >= dif_previous.macd_dif,
            "等待 15 分钟 DIF 走平或上行",
        ),
        (
            latest_bar.volume >= latest_indicator.volume_ma20 * config.minimum_volume_ratio,
            "等待 15 分钟成交量达到最低确认要求",
        ),
    ]

    invalidation_level = structure.invalidation_level or structure.pivot_low
    if invalidation_level is None or invalidation_level >= latest_bar.close:
        return EntryTriggerEvaluation(False, "60 分钟底结构缺少有效失效位")
    stop_distance = latest_bar.close - invalidation_level
    checks.append(
        (
            stop_distance / latest_bar.close <= config.maximum_stop_distance_pct
            and stop_distance <= latest_indicator.atr * config.maximum_stop_distance_atr,
            "触发价距离 60 分钟结构失效位过远，等待更合理的风险收益位置",
        )
    )

    failed_reasons = [reason for passed, reason in checks if not passed]
    if failed_reasons:
        return EntryTriggerEvaluation(
            False,
            "；".join(failed_reasons),
            trigger_ts=latest_bar.ts,
            trigger_price=latest_bar.close,
            trigger_level=breakout_level,
        )

    return EntryTriggerEvaluation(
        True,
        (
            f"15 分钟趋势恢复触发：收复 MA20、突破 {breakout_level:.2f}、"
            f"MACD 柱连续改善、DIF 上行、量能确认"
        ),
        trigger_ts=latest_bar.ts,
        trigger_price=latest_bar.close,
        trigger_level=breakout_level,
    )
