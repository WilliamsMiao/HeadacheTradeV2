from app.config import Settings
from app.models import TradePlan
from app.services.portfolio_manager import (
    check_sim_account_connection,
    futu_position_snapshot,
    get_portfolio_state,
    portfolio_sync_status,
)


class BrokenTradeProvider:
    def get_account_info(self):
        raise RuntimeError("OpenD trade context unavailable")


def test_portfolio_sync_error_becomes_capital_unknown(session):
    state = get_portfolio_state(session, BrokenTradeProvider(), Settings())
    saved = portfolio_sync_status(session)

    assert state.status == "CAPITAL_UNKNOWN"
    assert "无法确认模拟账户资金" in state.reason
    assert saved["ok"] is False
    assert "OpenD trade context unavailable" in saved["error"]


class WorkingTradeProvider:
    def get_account_info(self):
        return {"cash": 100000}

    def get_positions(self):
        return [{
            "code": "US.AAPL",
            "stock_name": "Apple",
            "qty": 10,
            "can_sell_qty": 8,
            "cost_price": 190,
            "market_val": 2000,
            "pl_val": 100,
            "pl_ratio": 5,
        }]

    def get_open_orders(self):
        return []


def test_read_only_sim_account_check_reports_all_connections(session):
    payload = check_sim_account_connection(session, WorkingTradeProvider(), Settings())
    assert payload["ok"] is True
    assert payload["account_connected"] is True
    assert payload["positions_connected"] is True
    assert payload["open_orders_connected"] is True
    assert payload["remote_positions"] == 1
    saved = portfolio_sync_status(session)
    assert saved["account_equity"] == 100000
    assert saved["account_equity_source"] == "FUTU_SIM_ACCOUNT"
    assert futu_position_snapshot(session) == [{
        "symbol": "US.AAPL",
        "name": "Apple",
        "qty": 10,
        "available_qty": 8,
        "cost_price": 190,
        "market_value": 2000,
        "pl_value": 100,
        "pl_ratio": 0.05,
        "currency": "USD",
    }]


def test_available_portfolio_state_is_written_to_active_plans(session):
    plan = TradePlan(
        symbol="AAPL", source_structure_id=1, battle_pool_id=1,
        structure_type="BOTTOM_STRUCTURE", priority_level="S", direction="LONG",
        stop_price=90, target_1=110, target_2=120, trailing_rule="trail",
        time_stop_rule="time", invalid_condition="invalid", risk_reward_1=1.5,
        risk_reward_2=2, status="ACTIVE", reason="test",
    )
    session.add(plan)
    session.commit()

    get_portfolio_state(session, WorkingTradeProvider(), Settings(max_positions=2))

    assert plan.capital_status == "CAPITAL_AVAILABLE"
    assert plan.capital_reason == ""
    assert plan.available_cash_snapshot == 100000
