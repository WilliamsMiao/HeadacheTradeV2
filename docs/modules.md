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

## 状态机与风控

`app.services.state_machine` 是唯一推动交易状态和建议生成的模块。评分字段只在 `TradeSignal.score_display` 展示，不参与状态转换。

入场建议必须有入场价、止损价、风险金额和股数。无止损位或组合风险不通过时，不允许生成入场建议。
