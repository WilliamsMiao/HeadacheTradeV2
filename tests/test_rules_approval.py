from app.config import Settings
from app.models import AuditLog, ReconciliationIssue, TradePlan
from app.services.portfolio_manager import PortfolioState
from app.services.rules_approval import rules_approve_trade_plan
from app.services.trade_reconciler import save_reconciliation_gate_status


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
    save_reconciliation_gate_status(session, {"allow_new_entries": True, "severity": "INFO", "open_issues": 0, "high_issues": 0, "critical_issues": 0, "reason": "ok"})
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


def test_high_reconciliation_issue_rejects_new_entry(session, monkeypatch):
    monkeypatch.setattr("app.services.rules_approval._entry_time_allowed", lambda settings: True)
    session.add(ReconciliationIssue(issue_type="SELL_ORDER_STUCK", symbol="US.EMR", severity="HIGH", status="OPEN", reason="对账发现风控卖单疑似卡住"))
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

    assert decision.decision == "REJECTED_BY_RECONCILIATION"
    assert "对账" in plan.rules_reject_reason
    assert session.query(AuditLog).filter_by(action="RULES_REJECTED_BY_RECONCILIATION").count() == 1


def test_critical_reconciliation_issue_rejects_new_entry(session, monkeypatch):
    monkeypatch.setattr("app.services.rules_approval._entry_time_allowed", lambda settings: True)
    session.add(ReconciliationIssue(issue_type="ACCOUNT_SYNC_FAILED", severity="CRITICAL", status="OPEN", reason="账户同步失败"))
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

    assert decision.decision == "REJECTED_BY_RECONCILIATION"


def test_warn_reconciliation_issue_does_not_block_new_entry(session, monkeypatch):
    monkeypatch.setattr("app.services.rules_approval._entry_time_allowed", lambda settings: True)
    session.add(ReconciliationIssue(issue_type="POSITION_COST_MISMATCH", severity="WARN", status="OPEN", reason="轻微成本差异"))
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


def test_info_reconciliation_issue_does_not_block_new_entry(session, monkeypatch):
    monkeypatch.setattr("app.services.rules_approval._entry_time_allowed", lambda settings: True)
    session.add(ReconciliationIssue(issue_type="BUY_ORDER_INFERRED_FILLED", severity="INFO", status="OPEN", reason="推断成交"))
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


def test_missing_reconciliation_gate_status_rejects_new_entry(session, monkeypatch):
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

    assert decision.decision == "REJECTED_BY_RECONCILIATION"
    assert "尚未完成交易对账" in decision.reason


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
