from app.models import BattlePoolItem, CandidateStock, Position, TradePlan
from app.presentation_status import status_for


def describe_trade_plan_next_action(plan: TradePlan) -> str:
    if plan.status in {"ACTIVE", "PLANNED"} and plan.breakout_entry_price:
        chase = f"，且不得高于 {plan.no_chase_above:.2f}" if plan.no_chase_above else ""
        return f"等待价格突破 {plan.breakout_entry_price:.2f}{chase}。"
    if plan.status == "NO_CHASE":
        return "不追单，等待价格回踩计划区或计划失效。"
    if plan.status in {"WAITLIST", "MISSED_BY_CAPITAL"}:
        return "资金释放后重新实时校验，不会直接下单。"
    if plan.status == "TRIGGERED":
        return "正在执行规则审批，通过后提交 Futu 模拟限价单。"
    if plan.status == "ORDER_SUBMITTED":
        return "等待模拟订单成交；超过等待时间将自动撤单。"
    return status_for(plan.status).next_action


def describe_position_next_action(position: Position) -> str:
    if position.current_r <= -0.7:
        return "接近止损，系统正在优先监控退出条件。"
    if position.partial_exit_done:
        return "已部分止盈，继续监控移动止盈和第二目标。"
    if position.current_r >= 1:
        return "已达到 1R，止损将抬至成本附近。"
    return "等待目标 1，同时持续监控硬止损。"


def describe_battle_next_action(item: BattlePoolItem, has_plan: bool) -> str:
    if has_plan:
        return "已有交易计划，进入实时价格与规则校验。"
    if item.priority_level in {"S", "A"}:
        return "等待形成明确止损和目标后生成交易计划。"
    return item.next_wait or "继续观察结构，不自动下单。"


def describe_candidate_next_action(status: str) -> str:
    actions = {
        "NO_STRUCTURE": "暂无 60 分钟结构，继续随小时监控。",
        "WAIT_CONFIRM": "等待结构确认，不能直接交易。",
        "STOP_TOO_WIDE": "等待止损距离收窄或新的结构。",
        "BATTLE_BUT_NOT_SA": "继续观察，B/C 级不会自动下单。",
        "PLAN_BLOCKED": "等待出现可推导明确止损和目标的结构。",
        "ACTIVE_PLAN": "已进入交易计划，等待实时校验。",
        "IN_POSITION": "已有持仓，优先管理风险。",
        "COOLDOWN": "冷却期内只观察，不生成新订单。",
        "DROPPED": "已退出当前候选池。",
    }
    return actions.get(status, "继续随系统监控。")
