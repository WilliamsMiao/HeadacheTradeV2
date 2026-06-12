import argparse
import json

from app.config import get_settings
from app.db import SessionLocal, init_db
from app.services.backtest import run_backtest
from app.services.battle_pool import rank_battle_pool
from app.services.pipeline import (
    run_60m,
    run_compute_indicators,
    run_daily,
    run_market_refresh,
    run_pipeline,
    run_scan_structures,
    run_screen_market,
    run_set_price_alerts,
    run_update_market_data,
)
from app.services.trade_plan import generate_trade_plans
from app.services.pipeline_lock import PipelineBusyError, pipeline_lock
from app.services.sim_loop import run_sim_loop
from app.providers.futu_trade_provider import FutuTradeProvider
from app.services.portfolio_manager import check_sim_account_connection


COMMANDS = (
    "init-db",
    "screen-market",
    "update-core-kline",
    "compute-indicators",
    "scan-structures",
    "rank-battle-pool",
    "generate-trade-plans",
    "set-price-alerts",
    "run-daily",
    "run-market-refresh",
    "run-60m",
    "run-pipeline",
    "run-backtest",
    "monitor-60m",
    "validate-trade-plans",
    "execute-sim-orders",
    "sync-sim-orders",
    "manage-positions",
    "run-sim-loop",
    "check-sim-account",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="HeadacheTradeV2 CLI")
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("--mock", action="store_true", help="仅供本地测试使用，不写入生产任务入口")
    args = parser.parse_args()
    settings = get_settings()
    init_db()
    if args.command == "check-sim-account":
        with SessionLocal() as session:
            provider = FutuTradeProvider(settings)
            try:
                payload = check_sim_account_connection(session, provider, settings)
            finally:
                provider.close()
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        if not payload.get("ok"):
            raise SystemExit(1)
        return
    try:
        with pipeline_lock():
            with SessionLocal() as session:
                if args.command == "init-db":
                    payload = {"status": "ok"}
                elif args.command == "screen-market":
                    payload = run_screen_market(session, settings, args.mock)
                elif args.command == "update-core-kline":
                    payload = run_update_market_data(session, settings, args.mock)
                elif args.command == "compute-indicators":
                    payload = {"computed": run_compute_indicators(session, settings)}
                elif args.command == "scan-structures":
                    payload = run_scan_structures(session, settings)
                elif args.command == "rank-battle-pool":
                    payload = rank_battle_pool(session)
                elif args.command == "generate-trade-plans":
                    payload = generate_trade_plans(session)
                elif args.command == "set-price-alerts":
                    payload = run_set_price_alerts(session, settings, args.mock)
                elif args.command == "run-daily":
                    payload = run_daily(session, settings, args.mock)
                elif args.command == "run-market-refresh":
                    payload = run_market_refresh(session, settings, args.mock)
                elif args.command == "run-60m":
                    payload = run_60m(session, settings, args.mock)
                elif args.command == "monitor-60m":
                    payload = run_60m(session, settings, args.mock)
                elif args.command in {
                    "validate-trade-plans",
                    "execute-sim-orders",
                    "sync-sim-orders",
                    "manage-positions",
                    "run-sim-loop",
                }:
                    payload = run_sim_loop(session, settings, args.mock)
                elif args.command == "run-pipeline":
                    payload = run_pipeline(session, settings)
                else:
                    payload = run_backtest(session, settings)
    except PipelineBusyError as exc:
        payload = {"status": "skipped", "reason": str(exc)}
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
