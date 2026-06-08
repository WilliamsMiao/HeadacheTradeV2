import argparse
import json

from app.config import get_settings
from app.db import SessionLocal, init_db
from app.services.backtest import run_backtest
from app.services.pipeline import run_compute_indicators, run_full_refresh, run_pipeline, run_sync_watchlist, run_update_market_data


def main() -> None:
    parser = argparse.ArgumentParser(description="HeadacheTradeV2 CLI")
    parser.add_argument("command", choices=["init-db", "sync-watchlist", "update-market-data", "compute-indicators", "run-pipeline", "run-backtest", "mock-full-refresh"])
    parser.add_argument("--mock", action="store_true", help="use mock provider instead of Futu OpenD")
    args = parser.parse_args()
    settings = get_settings()
    init_db()
    with SessionLocal() as session:
        if args.command == "init-db":
            payload = {"status": "ok"}
        elif args.command == "sync-watchlist":
            payload = {"synced": run_sync_watchlist(session, settings, args.mock)}
        elif args.command == "update-market-data":
            payload = run_update_market_data(session, settings, args.mock)
        elif args.command == "compute-indicators":
            payload = {"computed": run_compute_indicators(session, settings)}
        elif args.command == "run-pipeline":
            payload = run_pipeline(session, settings)
        elif args.command == "run-backtest":
            payload = run_backtest(session, settings)
        else:
            payload = run_full_refresh(session, settings, use_mock=True)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()

