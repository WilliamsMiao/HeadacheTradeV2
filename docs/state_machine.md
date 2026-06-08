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

