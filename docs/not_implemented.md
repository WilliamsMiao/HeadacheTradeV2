# 暂不实现内容

- 实盘自动下单。
- 做空、期权、高频交易。
- Order Flow、完整 ICT、谐波、斐波那契自动交易。
- 把评分作为买卖触发器。
- 参数优化覆盖核心规则。
- React Terminal WebSocket 实时推送。当前继续使用轮询，实施前必须完成
  [`websocket_proposal.md`](websocket_proposal.md) 中的 outbox、跨进程分发、续传和降级条件。

后续扩展必须作为辅助模块接入，不得绕过市场过滤、状态机和风控。
