# 状态机说明

主状态：

- `IDLE`
- `TREND_OK`
- `WATCH_BOTTOM`
- `BOTTOM_CONFIRMED`
- `WAIT_ENTRY_TRIGGER`
- `ENTRY_CANDIDATE`
- `IN_POSITION`
- `RISK_PROTECTION`
- `EXIT_CANDIDATE`
- `COOLDOWN`

硬约束：

- `RISK_OFF` 不允许进入 `ENTRY_CANDIDATE`。
- 冷却期内不允许新开仓。
- 数据异常时不得向更激进状态转换。
- 底结构只能推动等待趋势恢复，不能直接买入。
- 顶结构只推动风险保护或减仓候选，不能直接清仓。
- 入场候选必须先完成止损和仓位计算。
- 状态转换必须写入 `StateTransitionLog` 并记录原因。

## 多周期前置条件

交易核心数据必须同时具备 `1d / 60m / 15m` 的有效 K 线和最新指标。缺少任一核心周期时，状态机不得生成新的 ENTRY。

5m 仅用于后续工作台展示，缺失不会阻塞状态机。

当前状态仍保留 `WAIT_ENTRY_TRIGGER`；按任务书顺序，`WAIT_15M_TRIGGER` 和正式 15m 触发转换将在 PR 3 引入。

PR 2 提供的结构关键价位只用于记录和后续状态机输入。本 PR 不允许 `BOTTOM_STRUCTURE` 直接生成 ENTRY，也不允许 `TOP_STRUCTURE` 直接生成 EXIT。
