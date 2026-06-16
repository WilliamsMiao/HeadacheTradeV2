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
    "RECONCILIATION_ISSUE_OPEN": StatusPresentation("RECONCILIATION_ISSUE_OPEN", "对账问题待处理", "订单、成交、持仓或计划存在待确认的不一致。", "查看对账问题并等待同步恢复或人工处理。", "warning"),
    "RECONCILIATION_ISSUE_RESOLVED": StatusPresentation("RECONCILIATION_ISSUE_RESOLVED", "对账问题已恢复", "此前发现的不一致在最新对账中已消失。", "继续观察后续同步。", "success"),
    "REMOTE_POSITION_WITHOUT_LOCAL": StatusPresentation("REMOTE_POSITION_WITHOUT_LOCAL", "富途有仓本地无仓", "远端账户存在持仓，但本地没有 OPEN Position。", "运行持仓同步或人工核查账户。", "danger"),
    "LOCAL_POSITION_MISSING_REMOTE": StatusPresentation("LOCAL_POSITION_MISSING_REMOTE", "本地有仓富途无仓", "本地仍记录 OPEN Position，但远端账户没有对应持仓。", "等待同步确认或人工核查关闭来源。", "danger"),
    "POSITION_QTY_MISMATCH": StatusPresentation("POSITION_QTY_MISMATCH", "持仓数量不一致", "本地持仓数量与富途持仓数量不同。", "暂停新开仓并核查成交和持仓同步。", "danger"),
    "POSITION_COST_MISMATCH": StatusPresentation("POSITION_COST_MISMATCH", "持仓成本不一致", "本地入场价与富途成本价偏差超过阈值。", "核查成交价或成本同步来源。", "warning"),
    "REMOTE_ORDER_WITHOUT_LOCAL": StatusPresentation("REMOTE_ORDER_WITHOUT_LOCAL", "远端订单本地缺失", "富途 open orders 存在订单，但本地没有对应 SimOrder。", "核查订单来源并补全本地记录。", "warning"),
    "LOCAL_ORDER_MISSING_REMOTE": StatusPresentation("LOCAL_ORDER_MISSING_REMOTE", "本地订单远端缺失", "本地待对账订单未在远端挂单或成交中确认。", "继续订单和成交对账。", "warning"),
    "SELL_ORDER_STUCK": StatusPresentation("SELL_ORDER_STUCK", "风控卖单疑似卡住", "风控卖出单未在远端挂单或成交中确认。", "暂停新开仓并优先处理退出单。", "danger"),
    "BUY_ORDER_INFERRED_FILLED": StatusPresentation("BUY_ORDER_INFERRED_FILLED", "买入订单推断成交", "BUY 订单由远端持仓反推为成交。", "保留审计记录，后续用成交历史补全。", "info"),
    "CLOSE_UNVERIFIED": StatusPresentation("CLOSE_UNVERIFIED", "仓位关闭未验证", "仓位已从富途消失，但本地没有 SELL 成交确认。", "人工核查成交历史和盈亏。", "warning"),
    "ORDER_STATUS_UNKNOWN": StatusPresentation("ORDER_STATUS_UNKNOWN", "订单状态未知", "远端或本地订单状态无法映射到已知状态。", "保留原始响应并人工确认。", "warning"),
    "ACCOUNT_SYNC_FAILED": StatusPresentation("ACCOUNT_SYNC_FAILED", "账户同步失败", "读取远端订单、成交或持仓失败。", "检查 OpenD 和账户连接后重试。", "danger"),
    "RECONCILIATION_RUN_FAILED": StatusPresentation("RECONCILIATION_RUN_FAILED", "交易对账运行失败", "对账中枢运行异常，系统进入保护模式。", "检查异常原因，恢复后重新运行对账。", "danger"),
    "REJECTED_BY_RECONCILIATION": StatusPresentation("REJECTED_BY_RECONCILIATION", "交易对账闸门阻止", "存在未解决的高风险对账问题，自动新开仓被禁止。", "先处理对账问题；已有仓位仍会继续风控退出。", "danger"),
    "SELL_WAITING_RECONCILIATION": StatusPresentation("SELL_WAITING_RECONCILIATION", "卖出单待对账", "风控卖出单未在远端挂单列表中返回，系统等待成交或持仓同步确认。", "继续对账，超过阈值且持仓仍存在时可重试退出。", "warning"),
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
