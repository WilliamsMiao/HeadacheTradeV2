from dataclasses import dataclass


@dataclass(frozen=True)
class StatusPresentation:
    code: str
    display_name: str
    description: str
    next_action: str
    severity: str


STATUSES = {
    "ACTIVE": StatusPresentation("ACTIVE", "持续监控中", "计划仍然有效，系统正在等待价格和实时条件同时合适。", "继续监控价格和行情条件。", "info"),
    "PLANNED": StatusPresentation("PLANNED", "计划已生成", "结构价格框架已经生成，尚未进入实时执行。", "等待系统进入实时校验。", "neutral"),
    "ARMED": StatusPresentation("ARMED", "等待触发", "价格接近入场区，系统正在实时校验。", "若突破且未追高，将进入规则审批。", "info"),
    "TRIGGERED": StatusPresentation("TRIGGERED", "价格已到，等待审核", "价格已经进入计划区间，系统正在检查风险、资金和重复订单。", "全部检查通过后提交模拟限价单。", "success"),
    "ORDER_SUBMITTED": StatusPresentation("ORDER_SUBMITTED", "订单已提交", "模拟限价单已发送至 Futu。", "等待成交或超时撤单。", "success"),
    "IN_POSITION": StatusPresentation("IN_POSITION", "模拟持仓中", "模拟订单已成交，系统优先管理持仓风险。", "监控止损、目标位与移动止盈。", "success"),
    "WAIT_PULLBACK": StatusPresentation("WAIT_PULLBACK", "等待回踩", "价格突破后偏离计划区。", "等待价格回踩后重新校验，不追单。", "warning"),
    "NO_CHASE": StatusPresentation("NO_CHASE", "禁止追价", "当前价已超过禁止追价线，系统不会追单。", "等待回踩或计划失效。", "warning"),
    "WAITLIST": StatusPresentation("WAITLIST", "资金排队", "计划有效，但资金或持仓数量不允许开新仓。", "资金释放后重新实时校验。", "warning"),
    "MISSED_BY_CAPITAL": StatusPresentation("MISSED_BY_CAPITAL", "资金占用错过", "机会到价时资金已被其他持仓占用。", "记录后续表现，用于复盘资金效率。", "neutral"),
    "BLOCKED": StatusPresentation("BLOCKED", "风控阻止", "计划未通过组合或执行风控。", "等待阻塞原因解除后重新评估。", "danger"),
    "PAUSED": StatusPresentation("PAUSED", "暂停执行", "市场、数据或冷却条件暂不允许执行。", "条件恢复后重新校验。", "warning"),
    "INVALIDATED": StatusPresentation("INVALIDATED", "计划失效", "价格跌破止损或结构失效位。", "不再交易该计划。", "danger"),
    "EXPIRED": StatusPresentation("EXPIRED", "计划过期", "计划已超过有效期。", "等待新的结构和计划。", "neutral"),
}


def status_for(code: str | None) -> StatusPresentation:
    value = code or "UNKNOWN"
    return STATUSES.get(value, StatusPresentation(value, value, "系统状态暂无说明。", "查看详细原因。", "neutral"))
