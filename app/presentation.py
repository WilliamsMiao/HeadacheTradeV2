from __future__ import annotations

import re
import json
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo


LABELS: dict[str, str] = {
    "RISK_ON": "风险偏好，可开新仓",
    "NEUTRAL_POSITIVE": "中性偏强，谨慎开仓",
    "NEUTRAL_NEGATIVE": "中性偏弱，只管理持仓",
    "RISK_OFF": "风险关闭，禁止新仓",
    "1d": "日线",
    "60m": "60 分钟",
    "15m": "15 分钟",
    "5m": "5 分钟",
    "STRONG_UPTREND": "强上涨趋势",
    "UPTREND": "上涨趋势",
    "SIDEWAYS": "震荡观察",
    "DOWNTREND": "下跌趋势",
    "UNKNOWN": "数据不足",
    "DAILY_STRONG_BULL": "日线强多头",
    "DAILY_WEAK_BULL": "日线弱多头",
    "DAILY_RANGE": "日线震荡",
    "DAILY_WEAK_BEAR": "日线弱空头",
    "DAILY_STRONG_BEAR": "日线强空头",
    "IDLE": "空闲观察",
    "CANDIDATE_POOL": "候选池观察",
    "STRUCTURE_DETECTED": "已识别结构",
    "BATTLE_WATCH": "重点作战观察",
    "PLAN_READY": "交易计划已生成",
    "PRICE_ALERT_ARMED": "到价提醒已设置",
    "ENTRY_REVIEW": "等待入场复核",
    "SIM_POSITION": "模拟持仓",
    "EXIT_REVIEW": "等待退出复核",
    "TREND_OK": "趋势合格",
    "WATCH_BOTTOM": "底部观察",
    "BOTTOM_CONFIRMED": "底结构确认",
    "WAIT_ENTRY_TRIGGER": "等待入场触发",
    "WAIT_15M_TRIGGER": "等待 15 分钟触发",
    "ENTRY_CANDIDATE": "入场候选",
    "IN_POSITION": "持仓管理",
    "RISK_PROTECTION": "风险保护中",
    "EXIT_CANDIDATE": "退出候选",
    "COOLDOWN": "冷却期",
    "PLANNED": "计划已生成",
    "ARMED": "接近触发",
    "WAIT_PULLBACK": "等待回踩",
    "NO_CHASE": "禁止追价",
    "TRIGGERED": "规则触发",
    "ORDER_SUBMITTED": "模拟订单已提交",
    "WAITLIST": "资金排队",
    "MISSED_BY_CAPITAL": "因资金占用错过",
    "INVALIDATED": "计划失效",
    "PAUSED": "暂停执行",
    "BLOCKED": "风控阻止",
    "EXPIRED": "计划过期",
    "APPROVED_FOR_SIM_TRADE": "规则审批通过",
    "NOT_REVIEWED": "尚未规则审批",
    "REJECTED_BY_RISK": "风控拒绝",
    "REJECTED_BY_PRICE": "价格拒绝",
    "REJECTED_BY_MARKET": "市场环境拒绝",
    "REJECTED_BY_CAPITAL": "资金拒绝",
    "REJECTED_BY_DATA": "数据质量拒绝",
    "CAPITAL_AVAILABLE": "资金可用",
    "CAPITAL_LIMITED": "资金有限",
    "CAPITAL_FULL": "资金已满",
    "CAPITAL_CONFLICT": "资金冲突",
    "CAPITAL_UNKNOWN": "资金状态未知",
    "SUBMITTED": "已提交",
    "FILLED": "已成交",
    "PARTIALLY_FILLED": "部分成交",
    "CANCELLED": "已取消",
    "FAILED": "失败",
    "SIM_ORDER_SUBMITTED": "模拟订单已提交",
    "SIM_ORDER_FILLED": "模拟订单已成交",
    "SIM_ORDER_CANCELLED": "模拟订单已取消",
    "SIM_ORDER_FAILED": "模拟订单失败",
    "POSITION_OPENED": "模拟持仓已建立",
    "POSITION_CLOSED": "模拟持仓已关闭",
    "TRADE_PLAN_VALIDATED": "交易计划已实时校验",
    "RULES_APPROVED": "规则审批通过",
    "RULES_REJECTED": "规则审批拒绝",
    "MISSED_BY_CAPITAL": "因资金占用错过",
    "BOTTOM_PASSIVATION": "底钝化",
    "BOTTOM_STRUCTURE": "底结构",
    "BOTTOM_FAILED": "底结构失败",
    "TOP_PASSIVATION": "顶钝化",
    "TOP_STRUCTURE": "顶结构",
    "TOP_INVALIDATED": "顶结构失效",
    "LOW_REBOUND": "低位反弹池",
    "TREND_UP": "趋势上行池",
    "HIGH_RISK": "高位风险池",
    "WEAK_DOWN": "弱势下行池",
    "MACD_LOW_IMPROVING": "MACD 低位改善",
    "KDJ_LOW_GOLD_CROSS": "KDJ 低位金叉",
    "KDJ_BOTTOM_DIVERGENCE": "KDJ 底背离候选",
    "BOLL_CROSS_MIDDLE_UP": "BOLL 升穿中轨",
    "MA_ALIGNMENT_LONG": "均线多头排列",
    "EMA_ALIGNMENT_LONG": "指数均线多头排列",
    "BOLL_BREAK_UPPER": "BOLL 突破上轨",
    "MACD_DEATH_CROSS_HIGH": "MACD 高位死叉",
    "MACD_TOP_DIVERGENCE": "MACD 顶背离候选",
    "KDJ_DEATH_CROSS_HIGH": "KDJ 高位死叉",
    "RSI_TOP_DIVERGENCE": "RSI 顶背离候选",
    "MA_ALIGNMENT_SHORT": "均线空头排列",
    "EMA_ALIGNMENT_SHORT": "指数均线空头排列",
    "BOLL_CROSS_MIDDLE_DOWN": "BOLL 跌穿中轨",
    "LONG": "做多观察",
    "SHORT": "下行观察",
    "RISK": "风险观察",
    "PASSIVATION": "钝化阶段",
    "CONFIRMED": "结构确认",
    "FAILED": "结构失败",
    "INVALIDATED": "结构失效",
    "BREAKOUT": "突破入场复核",
    "BREAKOUT_OR_PULLBACK": "突破或回踩复核",
    "BREAKDOWN_REVIEW": "跌破复核",
    "NOT_ARMED": "未设置提醒",
    "ARMED": "提醒已设置",
    "ACTIVE": "有效",
    "ARCHIVED": "已归档",
    "TREND_RECOVERY": "趋势恢复",
    "TREND_BREAK": "趋势破坏",
    "BUY": "买入",
    "SELL": "卖出",
    "STOP": "止损",
    "TRAIL": "滑动止盈",
    "SCRIPT_A_BOTTOM_TREND_RESUME": "剧本 A：底结构后的趋势恢复",
    "SCRIPT_B_TOP_INVALIDATION_CONTINUATION": "剧本 B：顶结构失效后的强趋势再上",
    "ENTRY": "入场建议",
    "REDUCE": "减仓建议",
    "EXIT": "退出建议",
    "PENDING": "待审批",
    "APPROVED": "已批准",
    "REJECTED": "已拒绝",
    "EXPIRED": "已过期",
    "CANCELLED_BY_MARKET": "因市场降级取消",
    "CANCELLED_BY_STRUCTURE": "因结构失败取消",
    "CANCELLED_BY_TRIGGER": "因触发失败取消",
    "OPEN": "持仓中",
    "CLOSED": "已结束",
    "signal_count": "信号数",
    "position_count": "持仓数",
    "structure_count": "结构事件数",
    "win_rate": "胜率",
    "avg_r": "平均 R",
    "trade_count": "交易笔数",
    "median_r": "R 中位数",
    "max_drawdown": "最大回撤（R）",
    "max_consecutive_losses": "最大连续亏损",
    "avg_holding_period": "平均持有 K 线",
    "profit_factor": "盈亏因子",
    "exposure": "持仓暴露",
    "script_a_performance": "剧本 A 平均 R",
    "script_b_performance": "剧本 B 平均 R",
    "structure_success_rate": "结构触发成功率",
    "signal_expiry_rate": "信号过期率",
    "trigger_failure_rate": "触发失败率",
    "loss_count": "亏损笔数",
    "pipeline_states": "状态更新数",
}


REASON_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("market and stock trend passed, no structure opportunity", "市场与个股趋势通过，暂未出现结构机会"),
    ("data anomaly freezes new signals", "数据异常，冻结新入场建议"),
    ("daily data missing", "日线行情缺失，无法评估趋势"),
    ("60m data missing", "60 分钟行情缺失，无法确认短周期状态"),
    ("15m data missing", "15 分钟行情缺失，无法判断入场触发"),
    ("5m data missing; core trading is not blocked", "5 分钟行情缺失，仅影响辅助展示，不阻塞核心交易链路"),
    ("daily data anomaly", "日线行情异常"),
    ("60m data anomaly", "60 分钟行情异常"),
    ("15m data anomaly", "15 分钟行情异常"),
    ("repair market data, recompute indicators, then rerun pipeline", "重新更新行情、计算指标后，再刷新状态机"),
    ("data quality passed", "行情质量检查通过"),
    ("no bars returned from data source", "数据源未返回 K 线"),
    ("data missing or indicators unavailable", "行情或指标缺失"),
    ("market data or indicators missing", "市场行情或指标缺失"),
    ("market indicators insufficient", "市场指标历史不足"),
    ("daily or 60m data missing", "日线或 60 分钟数据缺失"),
    ("indicator history insufficient", "指标历史不足"),
    ("indicators missing at", "指标缺失，时间"),
    ("pending entry signal already exists", "已有待审批入场建议"),
    ("portfolio risk checks passed", "组合风险检查通过"),
    ("risk calculation failed or stop unavailable", "风控计算失败或止损位不清晰"),
    ("waiting for 15m trigger after structure", "等待 60 分钟底结构后的 15 分钟触发，结构"),
    ("60m bottom structure is no longer valid", "60 分钟底结构已经失败或失效"),
    ("15m trigger source is incomplete", "15 分钟触发来源不完整"),
    ("60m structure stop unavailable", "60 分钟结构止损无法计算"),
    ("market downgrade with 60m MA60 breakdown", "市场降级且个股跌破 60 分钟 MA60"),
    ("downgraded while position is open", "持仓期间市场状态降级"),
    ("generated by state machine, not score", "由状态机生成，评分未参与触发"),
    ("price recovered MA20, broke recent key high, MACD improved, volume acceptable, 60m not weak", "价格收复 MA20、接近/突破近期关键高点，MACD 改善，量能可接受，60 分钟不弱"),
    ("waiting for MA20 recovery, key high breakout, MACD improvement, volume confirmation, and 60m support", "等待收复 MA20、突破关键高点、MACD 改善、量能确认与 60 分钟支撑"),
    ("price near stage low while MACD DIF holds higher low and histogram improves", "价格接近阶段低位，DIF 未同步破低，MACD 柱改善"),
    ("price near stage high while MACD DIF fails to confirm and histogram weakens", "价格接近阶段高位，DIF 未同步创新高，MACD 柱走弱"),
    ("bottom passivation confirmed by key high breakout, MA20 recovery, MACD improvement, and acceptable volume", "底钝化后出现关键高点突破、收复 MA20、MACD 改善且量能可接受"),
    ("top passivation confirmed by key low break and continued MACD weakening", "顶钝化后跌破关键低点，MACD 继续走弱"),
    ("bottom structure failed after effective low break and renewed momentum deterioration", "底结构后有效破低，动能重新恶化"),
    ("top structure invalidated by renewed breakout with trend intact", "顶结构后重新突破，趋势仍未破坏"),
    ("hard stop triggered", "硬止损触发"),
    ("trend break exit candidate", "趋势破坏，进入退出候选"),
    ("trailing stop triggered", "滑动止盈触发"),
    ("top structure risk protection", "顶结构风险保护"),
    ("position held but latest data missing", "持仓中但最新数据缺失"),
    ("position healthy", "持仓状态正常"),
    ("manual approval created simulated position", "人工批准后创建模拟持仓"),
    ("manual approval reduced simulated position", "人工批准后模拟减仓"),
    ("simulated exit approved, cooldown started", "模拟退出已批准，进入冷却期"),
)


def label_for(value: Any) -> str:
    if value is None or value == "":
        return "-"
    key = str(value)
    return LABELS.get(key, key)


def css_class_for(value: Any) -> str:
    classes = {
        "RISK_ON": "market-risk-on",
        "NEUTRAL_POSITIVE": "market-neutral-positive",
        "NEUTRAL_NEGATIVE": "market-neutral-negative",
        "RISK_OFF": "market-risk-off",
    }
    return classes.get(str(value), "market-unknown")


def describe_market_state(value: Any) -> str:
    descriptions = {
        "RISK_ON": "市场趋势支持做多，可以寻找新机会。",
        "NEUTRAL_POSITIVE": "市场中性偏强，新仓需要降低风险。",
        "NEUTRAL_NEGATIVE": "市场偏谨慎，优先管理已有仓位。",
        "RISK_OFF": "市场风险较高，禁止生成新开仓建议。",
    }
    return descriptions.get(str(value), "市场状态尚未计算。")


def describe_market_reason(state: Any, reason: Any) -> str:
    raw_reason = str(reason or "")
    if "missing" in raw_reason or "insufficient" in raw_reason:
        return "市场基准数据或指标不完整，系统已保护性关闭新开仓。这不代表市场已经确认转弱。"
    if str(state) == "RISK_OFF":
        return "SPY 与 QQQ 均未通过长期趋势和动能过滤，因此暂停生成新开仓建议。"
    return describe_market_state(state)


def describe_script(value: Any) -> str:
    return label_for(value)


def format_reason(text: Any, limit: int | None = None) -> str:
    if text is None:
        return "-"
    result = str(text)
    for source, target in REASON_REPLACEMENTS:
        result = result.replace(source, target)
    result = re.sub(
        r"price near stage low ([0-9.]+) while MACD DIF holds a higher low and histogram improves",
        r"价格接近阶段低点 \1，DIF 未同步破低且 MACD 柱改善",
        result,
    )
    result = re.sub(
        r"price near stage high ([0-9.]+) while MACD DIF fails to confirm and histogram weakens",
        r"价格接近阶段高点 \1，DIF 未同步创新高且 MACD 柱走弱",
        result,
    )
    result = re.sub(
        r"bottom passivation confirmed above ([0-9.]+); pivot low ([0-9.]+); MA20 recovered, MACD improved, and volume accepted",
        r"底钝化后收盘突破确认位 \1；结构低点 \2；已收复 MA20，MACD 与量能确认",
        result,
    )
    result = re.sub(
        r"top passivation confirmed below ([0-9.]+); pivot high ([0-9.]+); MACD weakening continued",
        r"顶钝化后跌破确认位 \1；结构高点 \2；MACD 继续走弱",
        result,
    )
    result = re.sub(
        r"bottom structure failed below invalidation ([0-9.]+) with renewed MACD histogram deterioration",
        r"底结构跌破失效位 \1，MACD 柱重新恶化",
        result,
    )
    result = re.sub(
        r"top structure invalidated above ([0-9.]+) while price held above MA20",
        r"价格突破顶结构失效位 \1 且守住 MA20，顶结构失效",
        result,
    )
    result = re.sub(r"\bmarket state ([A-Z_]+) forbids new entries\b", lambda m: f"市场状态“{label_for(m.group(1))}”禁止新开仓", result)
    result = re.sub(
        r"\bmarket state ([A-Z_]+) downgraded while position is open\b",
        lambda m: f"持仓期间市场状态降级为“{label_for(m.group(1))}”",
        result,
    )
    result = re.sub(r"\bstock trend ([A-Z_]+) is not eligible\b", lambda m: f"个股趋势“{label_for(m.group(1))}”不符合开仓条件", result)
    result = result.replace("UPTREND", label_for("UPTREND"))
    result = result.replace("STRONG_上涨趋势", label_for("STRONG_UPTREND"))
    result = result.replace("STRONG_UPTREND", label_for("STRONG_UPTREND"))
    result = re.sub(
        r"\b60m data stale at ([0-9-]+); latest daily bar is ([0-9-]+)\b",
        r"60 分钟行情停留在 \1，落后于最新日线 \2",
        result,
    )
    result = re.sub(
        r"\b15m data stale at ([0-9-]+); latest daily bar is ([0-9-]+)\b",
        r"15 分钟行情停留在 \1，落后于最新日线 \2",
        result,
    )
    result = re.sub(r"\b15m indicators missing at\b", "15 分钟指标缺失，时间", result)
    result = re.sub(r"\b60m indicators missing at\b", "60 分钟指标缺失，时间", result)
    result = re.sub(r"\bdaily indicators missing at\b", "日线指标缺失，时间", result)
    result = re.sub(r"\bupdated ([0-9]+) bars; data quality passed\b", r"已更新 \1 根 K 线，质量检查通过", result)
    result = re.sub(
        r"\bupdated ([0-9]+) bars; ([0-9]+) anomalous bars isolated\b",
        r"已更新 \1 根 K 线，其中 \2 根异常数据已单独隔离",
        result,
    )
    result = re.sub(r"\bhas zero volume at ([0-9-]+ [0-9:]+)\b", r"在 \1 成交量为零", result)
    result = re.sub(r"\blow is inconsistent at ([0-9-]+ [0-9:]+)\b", r"在 \1 最低价字段不一致", result)
    result = re.sub(r"\bhigh is inconsistent at ([0-9-]+ [0-9:]+)\b", r"在 \1 最高价字段不一致", result)
    result = re.sub(r"\bstop=([0-9.]+)", r"止损=\1", result)
    result = re.sub(r"\bshares=([0-9]+)", r"建议股数=\1", result)
    result = re.sub(r"\bstop_source=60m bottom structure pivot ([0-9.]+) minus 0.5 ATR \(([0-9.]+)\)", r"止损来源=60 分钟底结构低点 \1 减去 0.5 倍 ATR（\2）", result)
    result = re.sub(r"\brisk_per_share=([0-9.]+)", r"每股风险=\1", result)
    result = re.sub(r"\ballowed_loss=([0-9.]+)", r"允许亏损=\1", result)
    result = re.sub(r"\bposition_value=([0-9.]+)", r"建议市值=\1", result)
    result = re.sub(r"\bstructure_id=([0-9]+)", r"结构编号=\1", result)
    result = re.sub(r"\bstructure_timeframe=60m", "结构周期=60 分钟", result)
    result = re.sub(r"\bstructure_ts=([^；;]+)", r"结构时间=\1", result)
    result = re.sub(r"\btrigger_timeframe=15m", "触发周期=15 分钟", result)
    result = re.sub(r"\btrigger_ts=([^；;]+)", r"触发时间=\1", result)
    result = re.sub(r"\btrigger_price=([0-9.]+)", r"触发价=\1", result)
    result = re.sub(r"\btrigger_level=([0-9.]+)", r"突破参考价=\1", result)
    result = result.replace("; ", "；")
    if limit and len(result) > limit:
        return result[: max(0, limit - 1)] + "…"
    return result


def format_money(value: Any) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "-"


def format_percent(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "-"


def format_shares(value: Any) -> str:
    try:
        return f"{int(value):,} 股"
    except (TypeError, ValueError):
        return "-"


def format_price(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "-"


def format_return(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{number * 100:+.1f}%"


def json_list(value: Any) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
        return [str(item) for item in parsed] if isinstance(parsed, list) else []
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


def format_datetime(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value) if value else "-"


def format_system_datetime(value: Any) -> str:
    if not isinstance(value, datetime):
        return format_datetime(value)
    utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return utc_value.astimezone(ZoneInfo("Asia/Hong_Kong")).strftime("%Y-%m-%d %H:%M")
