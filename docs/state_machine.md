# 状态机说明

主状态：

- `IDLE`
- `TREND_OK`
- `WATCH_BOTTOM`
- `BOTTOM_CONFIRMED`
- `WAIT_15M_TRIGGER`
- `ENTRY_CANDIDATE`
- `IN_POSITION`
- `RISK_PROTECTION`
- `EXIT_CANDIDATE`
- `COOLDOWN`

硬约束：

- `RISK_OFF` 不允许进入 `ENTRY_CANDIDATE`。
- 冷却期内不允许新开仓。
- 数据异常时不得向更激进状态转换。
- 60m 底结构只能推动 `BOTTOM_CONFIRMED → WAIT_15M_TRIGGER`，不能直接买入。
- 顶结构只推动风险保护或减仓候选，不能直接清仓。
- 入场候选必须先完成止损和仓位计算。
- 状态转换必须写入 `StateTransitionLog` 并记录原因。

## 多周期前置条件

交易核心数据必须同时具备 `1d / 60m / 15m` 的有效 K 线和最新指标。缺少任一核心周期时，状态机不得生成新的 ENTRY。

5m 仅用于后续工作台展示，缺失不会阻塞状态机。

## 入场状态链

`IDLE → TREND_OK → WATCH_BOTTOM → BOTTOM_CONFIRMED → WAIT_15M_TRIGGER → ENTRY_CANDIDATE`

- `BOTTOM_CONFIRMED` 是结构确认审计节点，不生成 ENTRY。
- `WAIT_15M_TRIGGER` 检查 15m MA20 收复、最近 8 根高点突破、MACD 柱连续改善、DIF 走平或上行、最低量能及结构失效位距离。
- 没有有效 60m `BOTTOM_STRUCTURE` 时，15m 再强也不能生成 ENTRY。
- ENTRY 原因必须记录 60m 结构编号/时间，以及 15m 触发时间/价格/突破参考价。

旧数据库中的 `WAIT_ENTRY_TRIGGER` 仅保留展示兼容，新状态转换不再写入该状态。
