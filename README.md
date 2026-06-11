# HeadacheTradeV2

基于 Futu OpenD、FastAPI 和 SQLite 的美股日线 + 60 分钟结构交易监控系统。

系统主流程：

`Futu 条件选股 -> 最多 300 支候选池 -> 日线状态 -> 60 分钟结构 -> S/A/B/C 评级 -> 重点作战池 -> 交易计划卡 -> 到价提醒`

## 核心原则

- 核心行情只依赖 `1d / 60m`。
- `15m / 5m` 仅作为可选增强，不阻断主流程。
- Futu 自选组不再是系统股票池入口。
- 市场风向标只提示仓位和节奏，不阻断选股、结构扫描或计划生成。
- 选股结果和结构事件都不是交易信号。
- 评分只用于候选排序和关注优先级，不直接触发买卖。
- 底结构不直接买入，顶结构不直接清仓。
- 没有明确结构止损和 ATR 时不得生成交易计划。
- 不接实盘自动下单；计划到价后仍需人工复核。

## 页面

- `/`：系统总览和每日/60 分钟任务。
- `/candidates`：低位反弹、趋势上行、高位风险、弱势下行四类候选池。
- `/structures`：60 分钟顶底结构事件。
- `/battle-pool`：S/A/B/C 重点作战评级。
- `/trade-plans`：入场区、止损、目标、移动止盈、时间止损和失效条件。
- `/market`：SPY + QQQ 市场风向标，仅供风险参考。
- `/opend`：OpenD 安装、配置、启动和验证码管理。

## 本地运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
cp .env.example .env
python -m app.cli init-db
uvicorn app.main:app --host 127.0.0.1 --port 8001
```

首次打开页面时设置系统独立访问密码。

## CLI

```bash
python -m app.cli screen-market
python -m app.cli update-core-kline
python -m app.cli compute-indicators
python -m app.cli scan-structures
python -m app.cli rank-battle-pool
python -m app.cli generate-trade-plans
python -m app.cli set-price-alerts
python -m app.cli run-daily
python -m app.cli run-60m
python -m app.cli run-backtest
```

`--mock` 只用于测试和本地开发，不在生产 Web 页面暴露。

## 生产部署

Ubuntu 24.04 + systemd + Nginx：

```bash
sudo bash deploy/install_server.sh
```

生产环境配置：

```bash
sudo nano /etc/headachetrade/headachetrade.env
sudo systemctl status headachetrade
sudo journalctl -u headachetrade -f
```

OpenD 默认安装到 `/opt/futu-opend`，只监听 `127.0.0.1:11111`。Futu 登录信息保存在服务器 `/etc/futu-opend/futu-opend.env`，不进入 SQLite 或 Git。

GitHub Actions 在 PR 上运行测试；合并到 `main` 后自动备份数据库、发布新版本、执行 SQLite 增量迁移、重启服务并检查 `/health`。
