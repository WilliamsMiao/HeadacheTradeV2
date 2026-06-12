from app.config import Settings
from app.models import TradePlan
from app.services.portfolio_manager import PortfolioState
from app.services.rules_approval import rules_approve_trade_plan


def triggered_plan():
    return TradePlan(
        symbol="AAPL",
        source_structure_id=1,
        battle_pool_id=1,
        structure_type="BOTTOM_STRUCTURE",
        priority_level="S",
        direction="LONG",
        breakout_entry_price=100,
        no_chase_above=102,
        stop_price=95,
        target_1=107.5,
        target_2=110,
        trailing_rule="trail",
        time_stop_rule="time",
        invalid_condition="invalid",
        risk_reward_1=1.5,
        risk_reward_2=2,
        status="TRIGGERED",
        reason="test",
    )


def test_capital_full_records_missed_by_capital(session, monkeypatch):
    monkeypatch.setattr("app.services.rules_approval._entry_time_allowed", lambda settings: True)
    plan = triggered_plan()
    session.add(plan)
    session.commit()
    decision = rules_approve_trade_plan(
        session,
        plan,
        {"current_price": 101, "spread_pct": 0.001, "volume_ok": True, "short_trend_ok": True, "market_state": "RISK_ON"},
        PortfolioState("CAPITAL_FULL", 0, 1, 0, "已达到最大持仓数"),
        Settings(enable_sim_trading=True),
    )
    assert decision.decision == "REJECTED_BY_CAPITAL"
    assert plan.status == "MISSED_BY_CAPITAL"
    assert plan.missed_by_capital_price == 101


def test_complete_rules_approve_sim_trade(session, monkeypatch):
    monkeypatch.setattr("app.services.rules_approval._entry_time_allowed", lambda settings: True)
    plan = triggered_plan()
    session.add(plan)
    session.commit()
    decision = rules_approve_trade_plan(
        session,
        plan,
        {"current_price": 101, "spread_pct": 0.001, "volume_ok": True, "short_trend_ok": True, "market_state": "RISK_ON"},
        PortfolioState("CAPITAL_AVAILABLE", 100000, 0, 0, "ok", 100000, 100000, "FUTU_SIM_ACCOUNT", "OK"),
        Settings(enable_sim_trading=True),
    )
    assert decision.approved
    assert plan.rules_approval_status == "APPROVED_FOR_SIM_TRADE"


def test_price_ready_plan_must_be_triggered_before_approval(session, monkeypatch):
    monkeypatch.setattr("app.services.rules_approval._entry_time_allowed", lambda settings: True)
    plan = triggered_plan()
    plan.status = "ACTIVE"
    session.add(plan)
    session.commit()
    decision = rules_approve_trade_plan(
        session,
        plan,
        {"current_price": 101, "spread_pct": 0.001, "volume_ok": True, "short_trend_ok": True, "market_state": "RISK_ON"},
        PortfolioState("CAPITAL_AVAILABLE", 100000, 0, 0, "ok", 100000, 100000, "FUTU_SIM_ACCOUNT", "OK"),
        Settings(enable_sim_trading=True),
    )
    assert decision.decision == "REJECTED_BY_PRICE"
    assert "尚未完整触发" in decision.reason
