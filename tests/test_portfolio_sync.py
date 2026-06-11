from app.config import Settings
from app.services.portfolio_manager import check_sim_account_connection, get_portfolio_state, portfolio_sync_status


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
        return [{"code": "US.AAPL"}]

    def get_open_orders(self):
        return []


def test_read_only_sim_account_check_reports_all_connections(session):
    payload = check_sim_account_connection(session, WorkingTradeProvider(), Settings())
    assert payload["ok"] is True
    assert payload["account_connected"] is True
    assert payload["positions_connected"] is True
    assert payload["open_orders_connected"] is True
    assert payload["remote_positions"] == 1
