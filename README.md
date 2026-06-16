# HeadacheTradeV2

> A simulation-first US stock trading operations system built around structure-based planning, Futu OpenD, FastAPI, SQLite, and auditable reconciliation.

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![SQLite](https://img.shields.io/badge/SQLite-local%20ledger-003B57?logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![Futu OpenD](https://img.shields.io/badge/Futu-OpenD%20SIM-1E66F5)](https://openapi.futunn.com/)
[![Tests](https://img.shields.io/badge/tests-pytest-success)](#quality)

HeadacheTradeV2 is a trading command center for US equities. It is designed to turn a fixed structure-trading workflow into a disciplined, auditable, simulation-only execution system.

The project focuses on the engineering work that serious trading systems need after a strategy is defined:

- clean watchlists and structure scanning
- explicit trade plans with stops, targets, and invalidation rules
- simulated order execution through Futu OpenD
- order, deal, position, and plan reconciliation
- protective gates that stop new entries when the ledger is unsafe
- terminal-grade visibility for plans, orders, positions, and journal data

This repository does **not** enable real-money auto trading. The current execution path is intentionally limited to Futu simulated trading, and `ENABLE_REAL_TRADING=true` is rejected by the application.

---

## Why This Exists

Most trading tools stop at signals. HeadacheTradeV2 is built for the harder part: keeping the trading loop accountable after a plan is created.

The system treats every automatic action as part of a ledger:

```text
Market data
  -> Candidate pool
  -> Daily state
  -> 60m structure
  -> Battle ranking
  -> Trade plan
  -> Realtime validation
  -> Sim order
  -> Futu order/deal/position sync
  -> Local position
  -> Reconciliation issues
  -> Protective gate
  -> Audit trail
```

The result is not just "can we place an order?" but "can we prove what happened, what is still unknown, and whether the system is safe to open another position?"

---

## Product Highlights

### Trading Workflow

- Fixed structure-based workflow for US equities.
- Core market data uses `1d` and `60m`; `15m` and `5m` are optional enhancements.
- Candidate pools separate low rebound, trend up, high risk, and weak down names.
- S/A/B/C battle ranking prioritizes attention without directly triggering trades.
- Trade plans contain entry zone, stop, target 1, target 2, trailing rule, time stop, and invalidation condition.
- Market state is advisory: it guides risk posture but does not directly create signals.

### Simulation-Only Execution

- Futu OpenD integration for simulated orders.
- No real trading provider path is exposed.
- Simulation safety check blocks startup if real trading is enabled.
- Entry orders and exit orders are handled differently.
- SELL risk orders use protective limit prices designed to be easier to fill.
- Target 1 partial exits are only confirmed after SELL fill confirmation.

### Four-Ledger Reconciliation

HeadacheTradeV2 reconciles:

- remote Futu open orders
- remote Futu deals
- remote Futu positions
- local `SimOrder`, `Position`, and `TradePlan` records

The reconciler records structured `ReconciliationIssue` rows for conditions such as:

- remote position without local position
- local position missing remotely
- quantity or cost mismatch
- local order missing remotely
- stuck SELL risk order
- inferred BUY fill
- unverified close
- account sync failure

### Protective Trading Gate

The reconciliation result is now a formal trading gate:

- `NORMAL`: ledger healthy, new entries allowed
- `DEGRADED`: WARN/INFO issues exist, new entries allowed
- `PROTECTIVE`: HIGH/CRITICAL issues exist, new entries blocked
- `SYNC_FAILED`: account/reconciliation failed, new entries blocked

Important safety rule: protective mode blocks **new BUY approvals only**. It does not block existing position management, stop loss exits, take profit exits, forced intraday exits, order sync, position sync, or SELL retry logic.

### Terminal Experience

The React terminal exposes a read-only operational view:

- system summary and capital status
- reconciliation mode and issue severity
- trade plans and validation checks
- positions and simulated orders
- timeline of structures, plans, orders, positions, and audits
- K-line context and plan overlays
- journal and performance summaries

The terminal currently uses importance-tiered polling. WebSocket design notes are tracked in [`docs/websocket_proposal.md`](docs/websocket_proposal.md).

---

## Screens And Routes

| Route | Purpose |
| --- | --- |
| `/` | Command dashboard and scheduled task overview |
| `/terminal` | React read-only trading terminal |
| `/candidates` | Candidate pools |
| `/structures` | 60m structure events |
| `/battle-pool` | S/A/B/C battle ranking |
| `/trade-plans` | Plans, price levels, checks, related orders and positions |
| `/sim-orders` | Simulated order ledger |
| `/positions` | Position ledger |
| `/journal` | Closed trade review |
| `/audit-logs` | Audit trail |
| `/market` | SPY/QQQ market state |
| `/risk` | Runtime risk settings |
| `/opend` | Futu OpenD setup and diagnostics |
| `/workbench/{symbol}` | Symbol-level research workbench |

Key terminal APIs include:

- `GET /api/terminal/summary`
- `GET /api/trade-plans`
- `GET /api/positions`
- `GET /api/sim-orders`
- `GET /api/timeline`
- `GET /api/journal/summary`
- `GET /api/kline`
- `GET /api/trade-plan-overlays`

---

## Architecture

```text
app/
  providers/              Futu and mock data/trade providers
  services/
    pipeline.py           daily and 60m processing pipeline
    trade_plan.py         plan generation
    realtime_execution_validator.py
    sim_order_executor.py simulated BUY submission
    order_sync.py         order/deal sync
    position_sync.py      Futu position sync and orphan detection
    position_manager.py   existing-position risk exits
    trade_reconciler.py   four-ledger reconciliation and gate state
    rules_approval.py     automated approval gates
    terminal_api.py       read-only terminal payloads
  templates/              server-rendered admin pages
frontend/
  src/                    React terminal
tests/                    pytest coverage for pipeline, risk, sync, terminal, reconciliation
deploy/                   systemd, nginx, and OpenD deployment helpers
docs/                     design notes and module documentation
```

The important boundary is intentional:

- strategy modules decide what is worth watching
- trade plan modules define the plan
- approval modules decide whether a new BUY is allowed
- position management modules protect existing exposure
- reconciliation modules decide whether the ledger is safe enough for new entries

---

## Quick Start

### 1. Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
```

If you use `uv`:

```bash
uv sync --extra test
```

### 2. Configure

Create `.env` from your deployment template or local settings.

Important defaults:

```dotenv
ENABLE_SIM_TRADING=true
ENABLE_REAL_TRADING=false
ENABLE_AUTO_APPROVAL=true
FUTU_HOST=127.0.0.1
FUTU_PORT=11111
MAX_POSITIONS=1
RISK_PER_TRADE_PCT=0.005
MAX_SYMBOL_POSITION_PCT=0.4
MAX_SPREAD_PCT=0.002
MAX_DAILY_NEW_TRADES=3
MAX_DAILY_LOSS_PCT=0.015
MAX_CONSECUTIVE_LOSSES=3
FORCE_INTRADAY_EXIT=true
NO_NEW_ENTRY_BEFORE_MINUTES_AFTER_OPEN=60
NO_NEW_ENTRY_BEFORE_CLOSE_MINUTES=30
```

### 3. Initialize

```bash
python -m app.cli init-db
```

### 4. Run

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Open `http://127.0.0.1:8001` and set the system access password on first launch.

---

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
python -m app.cli run-sim-loop
python -m app.cli run-backtest
```

Use `--mock` for local development and tests only.

---

## Sim Loop

The simulated execution loop is intentionally serialized:

```text
sync_sim_orders
sync_futu_positions_to_local
run_trade_reconciliation
save reconciliation_gate_status
manage_positions
get_portfolio_state
validate_active_trade_plans
rules_approve_trade_plan
execute_approved_sim_orders
rank_waitlisted_plans
```

This order matters:

- order and position sync get a chance to self-heal first
- reconciliation records remaining inconsistencies
- existing positions are still managed even when new entries are blocked
- new BUY approvals are blocked by HIGH/CRITICAL reconciliation issues

---

## Safety Model

HeadacheTradeV2 is designed around explicit safety constraints:

- no real-trading auto-order path
- every automatic BUY must pass risk, capital, realtime, and reconciliation gates
- HIGH/CRITICAL reconciliation issues block new entries
- WARN/INFO reconciliation issues remain visible but do not block entries
- SELL risk exits are never blocked by the reconciliation new-entry gate
- remote-missing SELL orders enter reconciliation state and can be retried with a bounded retry count
- remote-missing positions become `CLOSED_UNVERIFIED` unless a SELL fill confirms the close
- daily loss and consecutive loss rules only count verified closed positions

This is not financial advice and is not a production broker-dealer system. Treat it as a simulation-first trading operations project.

---

## Deployment

Ubuntu 24.04 + systemd + Nginx:

```bash
sudo bash deploy/install_server.sh
```

Useful production commands:

```bash
sudo nano /etc/headachetrade/headachetrade.env
sudo systemctl status headachetrade
sudo journalctl -u headachetrade -f
```

OpenD defaults:

- installed under `/opt/futu-opend`
- listens on `127.0.0.1:11111`
- credentials live in `/etc/futu-opend/futu-opend.env`
- credentials are not stored in SQLite or Git

GitHub Actions run tests on PRs. Merges to `main` deploy through the release workflow, including database backup, SQLite migration, service restart, and `/health` verification.

---

## Quality

Run the test suite:

```bash
uv run pytest -q
```

Current local verification after the reconciliation gate work:

```text
195 passed
```

The test suite covers:

- market data ingestion and freshness
- pipeline state transitions
- trade plan generation
- realtime validation
- risk approval
- simulated order execution
- Futu order and position sync
- reconciliation issue upsert/resolve
- protective gate behavior
- terminal API payloads
- legacy SQLite migrations

---

## Contributing

Contributions are welcome. The project is especially open to work in these areas:

- better reconciliation issue UI and workflow
- historical order/deal recovery
- Alembic migration support
- NYSE trading-day handling
- safer deployment and observability
- terminal UX improvements
- documentation and onboarding
- test coverage for edge cases around Futu OpenD responses

Please keep contributions aligned with the current scope:

- do not add new trading strategies without prior discussion
- do not add indicators casually
- do not introduce real-trading auto-execution
- preserve simulation-first safety checks
- add tests for behavior changes
- keep auditability and recovery paths explicit

Recommended workflow:

```bash
git checkout -b feature/your-change
uv run pytest -q
```

Then open a pull request with:

- what changed
- why it is safe
- what tests were run
- screenshots or payload examples for UI/API changes

---

## Roadmap

Near-term engineering priorities:

- ReconciliationIssue management page
- manual confirm / ignore / resolve workflow
- historical order recovery
- non-empty `futu_order_id` uniqueness constraints
- NYSE trading-day model
- Alembic migrations
- WebSocket terminal updates
- stronger web security hardening

---

## License

No license has been declared yet. If you plan to use or redistribute this project, open an issue first so the licensing intent can be clarified.
