# HeadacheTradeV2

美股结构趋势交易 MVP：Futu OpenD 数据源、FastAPI/Web、SQLite、本地模拟和复盘。

第一阶段目标不是追求收益率，而是跑通以下闭环：

`Futu 自选组同步 -> K 线采集 -> 指标计算 -> 市场/个股趋势过滤 -> 顶底结构识别 -> 状态机 -> 入场候选 -> 风控仓位 -> 人工审批模拟持仓 -> 减仓/退出 -> 复盘统计`

## 核心约束

- 评分只用于展示和排序，不参与买卖触发。
- 底结构只进入观察/等待趋势恢复，不能直接买入。
- 顶结构只进入风险保护/减仓候选，不能直接清仓。
- 新开仓必须通过市场环境过滤。
- 没有止损位不得生成入场建议。
- 系统只生成建议和模拟持仓，不接实盘自动下单。

## 运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
cp .env.example .env
python -m app.cli init-db
uvicorn app.main:app --host 127.0.0.1 --port 8001
```

CLI 入口：

```bash
python -m app.cli sync-watchlist
python -m app.cli update-market-data
python -m app.cli compute-indicators
python -m app.cli run-pipeline
python -m app.cli run-backtest
```

真实运行默认连接本机 Futu OpenD。Mock 数据源只用于测试和离线开发，不在 Web 侧边栏暴露入口；系统不会生成实盘订单。

## 生产部署

推荐 Ubuntu 24.04 + systemd + Nginx：

```bash
sudo bash deploy/install_server.sh
```

首次安装后检查：

```bash
sudo nano /etc/headachetrade/headachetrade.env
sudo systemctl status headachetrade
sudo journalctl -u headachetrade -f
```

GitHub Actions 自动部署需要在仓库 Secrets 中配置：

- `SERVER_HOST`：服务器公网 IP，例如 `47.237.149.132`
- `SERVER_USER`：用于 SSH 的用户，需可执行 `sudo`
- `SERVER_PORT`：SSH 端口，默认可不填
- `SERVER_SSH_KEY`：对应 SSH 私钥

工作流会在 `main` 分支 push 后运行测试，通过后打包代码上传到服务器并重启 `headachetrade.service`。

生产发布会在服务器缺少 OpenD 时自动安装 Futu OpenD。安装路径为 `/opt/futu-opend`，systemd 服务为 `futu-opend.service`，默认监听本机 `127.0.0.1:11111`。Futu 登录信息只保存在服务器本机，不进入 Git：

```bash
sudo nano /etc/futu-opend/futu-opend.env
sudo systemctl restart futu-opend
sudo systemctl status futu-opend
```

如果要改 OpenD 连接地址，在 `/etc/headachetrade/headachetrade.env` 中设置 `FUTU_HOST` 和 `FUTU_PORT`。
