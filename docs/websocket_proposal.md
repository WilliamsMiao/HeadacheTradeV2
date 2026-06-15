# React Terminal WebSocket 预研方案

## 结论

当前版本继续使用 React Query 轮询。暂不直接接入 WebSocket。

原因不是前端能力不足，而是交易状态由多个独立进程写入 SQLite：

- FastAPI Web 服务；
- 每 30 秒运行一次的模拟交易循环；
- 每根 60 分钟 K 线完成后运行的监控任务；
- 每日完整扫描任务。

这些进程之间没有事件总线。若现在只增加 FastAPI WebSocket，服务端仍需持续轮询 SQLite，
只是把浏览器轮询转移到了服务器，无法获得可靠的低延迟事件通知。

建议在满足实施条件后采用“数据库事务外盒 + 单一事件分发器 + WebSocket 网关”方案。

## 当前刷新基线

| 数据 | 当前刷新间隔 | 说明 |
| --- | ---: | --- |
| 选中标的 K 线 | 10 秒 | 只刷新当前 symbol |
| 计划详情、订单、持仓、覆盖线 | 15 秒 | 与模拟交易循环接近 |
| 事件时间线 | 15 秒 | 按当前 symbol 查询 |
| Terminal 总览、S/A 计划列表 | 30 秒 | 与 sim-loop 周期一致 |
| 结构事件、复盘统计 | 60 秒 | 不属于秒级执行数据 |

当前范围只覆盖选中标的、S/A 计划、当前持仓和近期订单，没有对 300 支候选池高频刷新。

## 目标

WebSocket 只负责通知“哪些数据已经变化”，不传输完整业务对象，也不执行交易逻辑。

客户端收到事件后，通过 TanStack Query 精确失效对应缓存，并继续使用现有只读 HTTP API
读取完整、稳定的数据契约。

```text
业务事务提交
  -> 写入 event_outbox
  -> 独立 dispatcher 读取未发布事件
  -> WebSocket gateway 按订阅范围广播
  -> React Query invalidateQueries
  -> 现有 GET /api/* 返回权威数据
```

该设计保留 HTTP API 作为唯一权威读模型，WebSocket 只做轻量失效通知。

## 事件范围

第一阶段只推送以下事件：

| 事件 | 触发来源 | 建议失效缓存 |
| --- | --- | --- |
| `trade_plan.updated` | 实时校验、规则审批、计划生成 | 计划列表、计划详情、覆盖线 |
| `order.updated` | 提交、成交、撤单、超时 | 订单、计划详情、时间线 |
| `position.updated` | 建仓、止损、止盈、移动止损 | 持仓、总览、计划详情、时间线 |
| `risk_stop.updated` | 资金同步、风控停止条件变化 | Terminal 总览 |
| `price.updated` | 当前选中标的报价 | 当前价、覆盖线、最新 K 线 |
| `kline.closed` | 60m 或日线任务完成 | 对应周期 K 线、结构事件 |

不推送：

- 全市场 300 支候选股的逐笔报价；
- tick 数据；
- 真实盘指令；
- Futu 登录密码、账户标识等敏感数据；
- 完整 K 线数组或完整交易计划详情。

## 消息契约

```json
{
  "event_id": 10482,
  "event_type": "trade_plan.updated",
  "occurred_at": "2026-06-15T14:32:08.120Z",
  "entity_type": "TradePlan",
  "entity_id": 31,
  "symbol": "US.NVDA",
  "version": 7,
  "reason": "status_changed",
  "data": {
    "status": "TRIGGERED"
  }
}
```

约束：

- `event_id` 单调递增，用于断线续传与去重；
- `version` 表示实体版本，旧消息不得覆盖新状态；
- `data` 只包含路由所需的最小字段；
- 所有时间使用带时区的 UTC ISO 8601；
- 未知事件类型必须被客户端安全忽略。

## 订阅模型

单个浏览器连接默认只订阅：

- Terminal 总览；
- S/A 交易计划；
- 当前持仓；
- 当前选中 symbol；
- 当前选中 TradePlan。

客户端切换标的时发送：

```json
{
  "action": "subscribe",
  "symbols": ["US.NVDA"],
  "trade_plan_ids": [31],
  "channels": ["summary", "plans", "orders", "positions", "timeline"]
}
```

服务端限制：

- 每个会话最多订阅 5 个 symbol；
- 每个会话最多订阅 20 个 TradePlan；
- 禁止订阅全市场价格频道；
- 服务端忽略客户端提交的账户、用户或交易环境标识。

## 跨进程事件发布

### 推荐方案：SQLite Outbox

新增 `event_outbox` 表：

```text
id
event_type
entity_type
entity_id
symbol
entity_version
payload_json
created_at
published_at
attempt_count
last_error
```

业务模块必须在更新交易实体的同一数据库事务内写入 outbox。这样可以避免“数据库已更新但
事件丢失”或“事件已发送但事务回滚”。

新增独立 `headachetrade-event-dispatcher.service`：

- 每 250–500ms 批量读取未发布事件；
- 发布成功后更新 `published_at`；
- 失败指数退避；
- 保留最近事件用于短时续传；
- 每批数量有上限，避免阻塞 SQLite。

单机 MVP 不需要先引入 Redis。只有出现多实例 FastAPI、事件积压或 SQLite 写锁压力时，
再评估 Redis Streams 或 PostgreSQL `LISTEN/NOTIFY`。

### 不采用的方案

- FastAPI 进程内队列：无法接收 systemd 任务进程产生的事件，重启即丢失；
- WebSocket 网关轮询全部业务表：查询重、难以判断变化原因，仍然不是事件驱动；
- 直接从 sim-loop 连接浏览器：生命周期、安全和部署边界错误；
- 每个报价都写 SQLite：写放大明显，不适合当前架构。

## FastAPI 接口

未来新增：

```text
GET /api/events/cursor
WS  /api/ws/terminal?cursor=<last_event_id>
```

认证要求：

- 复用现有全站登录会话 Cookie；
- WebSocket 握手时校验登录态；
- 校验 `Origin`，仅允许当前站点；
- 未登录、会话过期或来源不合法时立即关闭；
- Terminal 保持只读，WebSocket 不接受交易操作。

建议关闭码：

| 关闭码 | 含义 |
| --- | --- |
| `4401` | 未登录或会话过期 |
| `4403` | 来源或订阅范围不允许 |
| `4408` | 心跳超时 |
| `4429` | 连接或消息频率超限 |
| `4500` | 服务端暂时不可用 |

## 客户端策略

新增 `useTerminalEvents`，只负责连接状态与缓存失效：

```text
trade_plan.updated
  -> invalidate ['trade-plans']
  -> invalidate ['trade-plan-detail', id]
  -> invalidate ['trade-plan-overlay', id]

order.updated
  -> invalidate ['orders']
  -> invalidate ['orders', symbol]
  -> invalidate ['timeline', symbol]

position.updated
  -> invalidate ['positions']
  -> invalidate ['positions', symbol]
  -> invalidate ['terminal-summary']

kline.closed
  -> invalidate ['kline', symbol, timeframe]
  -> timeframe == 60m 时 invalidate ['structures', symbol, '60m']
```

高频 `price.updated` 需要按 symbol 合并，前端最多每秒更新一次界面，避免图表重绘风暴。

## 断线、续传与降级

1. 客户端保存最后处理的 `event_id`。
2. 重连使用指数退避：1、2、5、10、30 秒，最大 30 秒。
3. 重连时携带 `cursor`，服务端补发仍在保留窗口内的事件。
4. cursor 太旧时返回 `resync_required`，客户端统一失效 Terminal 查询。
5. WebSocket 断开超过 10 秒后自动启用现有轮询频率。
6. 连接恢复并完成一次全量同步后，降低或关闭执行数据轮询。
7. 浏览器离线时停止重连；`online` 事件触发后重新连接。

WebSocket 状态必须显示为自然语言：

- 实时连接正常；
- 正在重新连接，数据继续按轮询刷新；
- 实时连接不可用，当前使用定时刷新；
- 数据已超过新鲜度阈值。

## 心跳

- 服务端每 20 秒发送 `ping`；
- 客户端 10 秒内回复 `pong`；
- 40 秒无有效通信关闭连接；
- 心跳只证明连接存活，不代表行情、sim-loop 或资金同步正常；
- Terminal 顶部仍需分别展示行情、交易、资金同步和 sim-loop 新鲜度。

## 容量与性能

单机初始目标：

- 50 个并发浏览器连接；
- 每个连接 1 个选中 symbol；
- 每秒最多 10 个业务事件；
- 消息体控制在 2KB 内；
- dispatcher 单批最多 100 条；
- outbox 已发布事件保留 24 小时后清理。

必须监控：

- 活跃连接数；
- outbox 未发布数量与最老事件年龄；
- 发布失败次数；
- 每类事件速率；
- 客户端重连次数；
- `resync_required` 次数；
- SQLite busy/locked 次数。

## 分阶段实施

### WS-0：可观测性准备

- 为 sim-loop、订单同步、持仓管理、60m 任务增加明确心跳记录；
- 为 TradePlan、SimOrder、Position 增加稳定版本或更新时间语义；
- 统一 React Query key，避免事件到达后无法精确失效。

### WS-1：Outbox 与分发器

- 新增 outbox 表及迁移；
- 在计划、订单、持仓和风险状态事务中写事件；
- 新增 dispatcher 与积压监控；
- 暂不开放浏览器 WebSocket。

### WS-2：只读 WebSocket 网关

- 增加认证握手、订阅限制、心跳和 cursor 续传；
- 先推送计划、订单、持仓、风险停止事件；
- 保留完整轮询作为降级路径。

### WS-3：选中标的报价

- 只为活跃订阅 symbol 获取或转发报价；
- 服务端和客户端都做合并节流；
- 禁止扩展为 300 支候选池的逐笔推送。

### WS-4：运行评估

连续观察至少 5 个美股交易日：

- 事件延迟；
- 丢失与重复；
- SQLite 锁；
- 重连稳定性；
- 相比轮询减少的请求量。

只有数据证明轮询成为瓶颈，才考虑 Redis Streams、PostgreSQL 或多实例部署。

## 实施门槛

开始 WS-1 前必须满足：

- 当前轮询版本稳定运行至少 5 个交易日；
- sim-loop、订单同步、持仓管理的心跳可以独立判断；
- 生产数据库有自动备份与迁移回滚流程；
- 事件重复处理是幂等的；
- 浏览器断线不会影响自动模拟交易；
- WebSocket 故障时现有 HTTP 轮询能自动接管。

## 验收标准

- WebSocket 只读，无法提交、修改或取消订单；
- sim-loop 与 FastAPI 任一进程重启后事件不丢失；
- 重复事件不会造成 UI 状态倒退；
- 切换 symbol 后旧标的事件不会污染当前图表；
- 连接中断时 10 秒内恢复轮询；
- 连接恢复时能续传或执行完整重同步；
- 计划、订单、持仓状态在业务提交后 2 秒内显示；
- 300 支候选池不会产生高频推送；
- 真实交易继续永久禁用。

