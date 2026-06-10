# 模块说明

## 数据采集

`app.providers.futu_provider.FutuProvider` 只负责读取 Futu OpenD 的自选组和 K 线数据，不生成交易信号。`app.services.data_ingestion` 负责自选股同步、K 线质量检查和 SQLite 写入。

统一周期定义位于 `app.domain`：

- 核心周期：`1d / 60m / 15m`；
- 展示周期：`5m`；
- 趋势周期：`1d`；
- 结构周期：`60m`；
- 触发周期：`15m`。

默认数据任务只拉取核心周期。`FUTU_INCLUDE_5M=true` 时额外拉取 5m。5m 缺失只影响工作台辅助展示，不阻塞交易状态机。

数据异常、缺失、零成交量或 OHLC 不一致会写入 `KLine.data_ok=false`。任一核心周期缺少最新 K 线或对应指标时，流水线会冻结新入场建议。

## 指标

`app.services.indicators` 对 `1d / 60m / 15m` 按时间顺序计算 MA20、MA60、MACD DIF、DEA、MACD 柱、ATR、成交量均线。指标表与原始行情表分离，指标模块不负责买卖判断。

## 市场与趋势

市场环境默认用 `SPY + QQQ`，输出 `RISK_ON / NEUTRAL_POSITIVE / NEUTRAL_NEGATIVE / RISK_OFF`。新开仓只允许在 `RISK_ON` 或 `NEUTRAL_POSITIVE`。

个股趋势输出 `STRONG_UPTREND / UPTREND / SIDEWAYS / DOWNTREND / UNKNOWN`。只有 `STRONG_UPTREND` 和 `UPTREND` 能进入新开仓候选。

## 结构识别

结构模块只写 `StructureEvent`，包括底钝化、底结构、底结构失败、顶钝化、顶结构、顶结构失效。结构事件不会直接产生买卖动作。

60m `BOTTOM_STRUCTURE` 必须记录结构低点、确认价、失效价、到期时间和规则版本；`TOP_STRUCTURE` 必须记录结构高点及相同审计字段。失败/失效事件通过 `parent_event_id` 关联原结构，并结束对应结构生命周期。

结构参数集中在 `app.strategy_config.StructureConfig`，不得在识别函数中散落阈值。

状态机和主看板只读取 `STRUCTURE_TIMEFRAME` 指定的 60m 结构；旧数据库中遗留的日线结构记录仅保留用于历史审计，不再推动当前状态。

## 状态机与风控

`app.services.state_machine` 是唯一推动交易状态和建议生成的模块。评分字段只在 `TradeSignal.score_display` 展示，不参与状态转换。

`app.services.entry_trigger` 只评估有效 60m 底结构之后的 15m 趋势恢复。它不会独立创建信号，也不能绕过市场状态、日线趋势、组合风控或止损检查。

剧本 A 的初始止损由 `app.services.risk.calculate_structure_stop` 计算：`60m BOTTOM_STRUCTURE.pivot_low - 0.5 × 结构时点 60m ATR`。缺少结构低点、结构时点 ATR 或有效触发来源时，不允许生成入场建议。

ENTRY 建议持久化结构编号、15m 触发时间/参考价、每股风险、允许亏损、实际风险、建议市值和规则版本。仓位继续按允许亏损反推，评分不参与仓位计算。

## 纠错机制

`app.services.corrections` 在状态机推进和人工审批前检查未审批 ENTRY：

- 来源底结构失败：`CANCELLED_BY_STRUCTURE` 并进入冷却；
- 触发后 5 根 15m K 内跌回触发位、MA20 下方或 MACD 柱转弱：`CANCELLED_BY_TRIGGER`；
- 超过 4 根 15m K 仍未审批：`EXPIRED`；
- 市场降级至不可开仓状态：`CANCELLED_BY_MARKET`。

取消只改变建议状态并记录 `cancel_reason`，不会删除原记录，也不会执行实盘订单。持仓期间市场降级会进入风险保护；若同时跌破 60m MA60，只生成待人工审批的退出候选。

## 时间步进回测

`app.services.backtest` 将原始 K 线逐步暴露到隔离数据库，并复用市场、趋势、结构、状态机、纠错、风控和审批模块。回测结果写入 `BacktestTrade`，系统统计写入 `ReviewStat`；实时 `TradeSignal` 和 `Position` 不会被回测污染。
