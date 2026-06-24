from datetime import UTC, datetime

from app.main import app
from app.config import Settings
from app.models import (
    BattlePoolItem,
    CandidateStock,
    KLine,
    Position,
    ReconciliationIssue,
    SimOrder,
    AuditLog,
    StructureEvent,
    SystemConfig,
    TradePlan,
)
from app.services.terminal_api import (
    cached_terminal_summary,
    clear_terminal_summary_cache,
    daily_stats_payload,
    first_valid_trade_payload,
    journal_summary_payload,
    kline_payload,
    orders_payload,
    positions_payload,
    structures_payload,
    terminal_summary,
    timeline_payload,
    trade_plan_overlay_payload,
    trade_plan_detail,
    trade_plan_list,
)


def _plan(symbol: str = "US.AAPL", priority: str = "S") -> TradePlan:
    return TradePlan(
        symbol=symbol,
        name="Apple",
        direction="LONG",
        source_structure_id=1,
        battle_pool_id=1,
        daily_state="DAILY_STRONG_BULL",
        structure_type="BOTTOM_STRUCTURE",
        priority_level=priority,
        breakout_entry_price=180,
        no_chase_above=182,
        current_price=181,
        stop_price=175,
        target_1=187.5,
        target_2=190,
        trailing_rule="盈利后逐步抬高止损。",
        time_stop_rule="三根 60 分钟 K 线未走强则失效。",
        invalid_condition="跌破结构低点。",
        risk_reward_1=1.5,
        risk_reward_2=2,
        status="ACTIVE",
        reason="日线强势且 60 分钟底结构确认。",
    )


def test_terminal_summary_uses_futu_sim_account_equity(session):
    session.add(SystemConfig(
        key="portfolio_sync_status",
        value=(
            '{"ok": true, "status": "CAPITAL_AVAILABLE", "account_equity": 1000000, '
            '"available_cash": 800000, "account_equity_source": "FUTU_SIM_ACCOUNT", '
            '"account_equity_sync_status": "OK", "updated_at": "2026-06-12T06:00:00+00:00"}'
        ),
    ))
    session.commit()

    payload = terminal_summary(session, Settings())

    assert payload["account_equity"] == 1000000
    assert payload["account_equity_source"] == "FUTU_SIM_ACCOUNT"
    assert payload["real_trading"] == "DISABLED"
    assert payload["can_open_new_position"] is True
    assert payload["reconciliation"]["open_issues"] == 0


def test_terminal_summary_exposes_reconciliation_status(session):
    session.add(
        ReconciliationIssue(
            symbol="US.EMR",
            issue_type="SELL_ORDER_STUCK",
            severity="HIGH",
            status="OPEN",
            reason="风控卖单疑似卡住",
        )
    )
    session.commit()

    payload = terminal_summary(session, Settings())

    assert payload["reconciliation"]["open_issues"] == 1
    assert payload["reconciliation"]["high_issues"] == 1
    assert payload["reconciliation"]["severity"] == "HIGH"
    assert payload["reconciliation"]["allow_new_entries"] is False


def test_trade_plan_list_orders_s_before_a_and_exposes_display_state(session):
    session.add_all([_plan("US.MSFT", "A"), _plan("US.AAPL", "S")])
    session.commit()

    plans = trade_plan_list(session, Settings(), priority="S,A")

    assert [plan["priority_level"] for plan in plans] == ["S", "A"]
    assert plans[0]["display_status"]["display_name"] == "持续监控中"
    assert plans[0]["next_system_action"]
    assert plans[0]["checks"]


def test_trade_plan_list_limit_caps_results(session):
    for index in range(5):
        session.add(_plan(f"US.T{index}", "A"))
    session.commit()

    plans = trade_plan_list(session, Settings(), active_only=False, limit=2)

    assert len(plans) == 2


def test_terminal_summary_cache_can_reuse_short_lived_payload(session):
    settings = Settings(summary_cache_ttl_seconds=2)
    session.add(SystemConfig(
        key="portfolio_sync_status",
        value=(
            '{"ok": true, "status": "CAPITAL_AVAILABLE", "account_equity": 1000000, '
            '"available_cash": 800000, "account_equity_source": "FUTU_SIM_ACCOUNT", '
            '"account_equity_sync_status": "OK", "updated_at": "2026-06-12T06:00:00+00:00"}'
        ),
    ))
    session.commit()
    clear_terminal_summary_cache()

    first = cached_terminal_summary(session, settings)
    config = session.query(SystemConfig).filter(SystemConfig.key == "portfolio_sync_status").one()
    config.value = (
        '{"ok": true, "status": "CAPITAL_AVAILABLE", "account_equity": 2000000, '
        '"available_cash": 1800000, "account_equity_source": "FUTU_SIM_ACCOUNT", '
        '"account_equity_sync_status": "OK", "updated_at": "2026-06-12T06:00:01+00:00"}'
    )
    session.commit()
    second = cached_terminal_summary(session, settings)
    clear_terminal_summary_cache()
    third = cached_terminal_summary(session, settings)

    assert first["account_equity"] == 1000000
    assert second["account_equity"] == 1000000
    assert third["account_equity"] == 2000000


def test_trade_plan_detail_returns_complete_readonly_chain(session):
    structure = StructureEvent(
        symbol="US.AAPL",
        timeframe="60m",
        event_type="BOTTOM_STRUCTURE",
        event_ts=datetime.now(UTC).replace(tzinfo=None),
        price=178,
        reason="底结构确认。",
    )
    session.add(structure)
    session.flush()
    battle = BattlePoolItem(
        symbol="US.AAPL",
        direction="LONG",
        priority_level="S",
        source_structure_id=structure.id,
        daily_state="DAILY_STRONG_BULL",
        structure_type="BOTTOM_STRUCTURE",
        score=92,
        reason="日线与结构共振。",
        status="ACTIVE",
    )
    session.add(battle)
    session.flush()
    plan = _plan()
    plan.source_structure_id = structure.id
    plan.battle_pool_id = battle.id
    session.add_all([
        CandidateStock(
            symbol="US.AAPL",
            name="Apple",
            pool_type="TREND_UP",
            selected_reason="趋势上行池。",
            rank_score=90,
        ),
        plan,
    ])
    session.commit()

    detail = trade_plan_detail(session, plan, Settings())

    assert detail["candidate"]["symbol"] == "US.AAPL"
    assert detail["structure_event"]["id"] == structure.id
    assert detail["battle_item"]["priority_level"] == "S"
    assert detail["trade_plan"]["id"] == plan.id
    assert detail["realtime_checks"]
    assert detail["related_orders"] == []
    assert detail["related_position"] is None


def test_position_and_order_payloads_are_empty_safe(session):
    assert positions_payload(session) == []
    assert orders_payload(session) == []


def test_timeline_payload_aggregates_and_orders_trade_chain(session):
    structure = StructureEvent(
        symbol="US.AAPL",
        timeframe="60m",
        event_type="BOTTOM_STRUCTURE",
        event_ts=datetime(2026, 6, 12, 14, 30),
        price=178,
        reason="底结构确认。",
    )
    session.add(structure)
    session.flush()
    battle = BattlePoolItem(
        symbol="US.AAPL",
        direction="LONG",
        priority_level="S",
        source_structure_id=structure.id,
        daily_state="DAILY_STRONG_BULL",
        structure_type="BOTTOM_STRUCTURE",
        score=92,
        reason="结构与日线共振。",
        status="ACTIVE",
    )
    plan = _plan()
    plan.source_structure_id = structure.id
    session.add_all([battle, plan])
    session.flush()
    session.add_all([
        SimOrder(
            trade_plan_id=plan.id,
            symbol="US.AAPL",
            side="BUY",
            qty=100,
            limit_price=180,
            status="FILLED",
            dealt_qty=100,
            dealt_avg_price=180,
        ),
        Position(
            symbol="US.AAPL",
            status="OPEN",
            entry_price=180,
            stop_price=175,
            shares=100,
            risk_amount=500,
            source_trade_plan_id=plan.id,
        ),
        AuditLog(
            action="RULES_APPROVED",
            symbol="US.AAPL",
            subject_type="TradePlan",
            subject_id=plan.id,
            status="SUCCESS",
            reason="规则审批通过。",
        ),
    ])
    session.commit()

    events = timeline_payload(session, "us.aapl", limit=20)

    assert {"STRUCTURE", "BATTLE_POOL", "TRADE_PLAN", "SIM_ORDER", "POSITION"}.issubset(
        {event["type"] for event in events}
    )
    assert any(event["id"].startswith("audit-") for event in events)
    assert [event["time"] for event in events] == sorted(
        [event["time"] for event in events], reverse=True
    )


def test_timeline_payload_is_empty_safe_and_requires_symbol(session):
    assert timeline_payload(session, "US.EMPTY") == []
    try:
        timeline_payload(session, "")
    except ValueError as exc:
        assert "股票代码不能为空" in str(exc)
    else:
        raise AssertionError("blank symbol must be rejected")


def test_journal_summary_uses_closed_positions_only_and_calculates_drawdown(session):
    session.add_all([
        Position(symbol="US.WIN", status="CLOSED", entry_price=100, stop_price=95,
                 shares=10, risk_amount=50, current_r=2),
        Position(symbol="US.LOSS", status="CLOSED", entry_price=100, stop_price=95,
                 shares=10, risk_amount=50, current_r=-1),
        Position(symbol="US.OPEN", status="OPEN", entry_price=100, stop_price=95,
                 shares=10, risk_amount=50, current_r=5),
    ])
    session.commit()

    payload = journal_summary_payload(session)

    assert payload["closed_trades"] == 2
    assert payload["wins"] == 1
    assert payload["win_rate"] == 0.5
    assert payload["cumulative_r"] == 1
    assert payload["max_drawdown_r"] == -1
    assert len(payload["curve"]) == 2


def test_daily_stats_groups_rejections_and_marks_missed_follow_up_as_observation(session):
    plan = _plan()
    plan.status = "MISSED_BY_CAPITAL"
    plan.missed_by_capital_price = 100
    plan.current_price = 105
    session.add_all([
        plan,
        AuditLog(action="RULES_REJECTED", symbol="US.AAPL", status="REJECTED",
                 reason="市场风险较高"),
        AuditLog(action="RULES_REJECTED", symbol="US.MSFT", status="REJECTED",
                 reason="市场风险较高"),
    ])
    session.commit()

    payload = daily_stats_payload(session)

    assert payload["rejection_reasons"][0] == {"reason": "市场风险较高", "count": 2}
    assert payload["missed_opportunities"][0]["follow_up_pct"] == 5
    assert payload["missed_opportunities"][0]["status_display_name"] == "资金占用错过"


def test_first_valid_trade_uses_first_real_position_of_each_day(session):
    session.add_all([
        Position(symbol="US.FIRST", status="CLOSED", entry_price=100, stop_price=95,
                 shares=10, risk_amount=50, current_r=1),
        Position(symbol="US.SECOND", status="CLOSED", entry_price=100, stop_price=95,
                 shares=10, risk_amount=50, current_r=2),
    ])
    session.commit()

    payload = first_valid_trade_payload(session)

    assert len(payload) == 1
    assert payload[0]["symbol"] == "US.FIRST"
    assert payload[0]["result_r"] == 1


def test_position_and_order_payloads_keep_raw_numeric_values(session):
    plan = _plan()
    session.add(plan)
    session.flush()
    position = Position(
        symbol="US.AAPL",
        status="OPEN",
        entry_price=180,
        stop_price=175,
        shares=100,
        risk_amount=500,
        current_r=0.5,
        source_trade_plan_id=plan.id,
    )
    order = SimOrder(
        trade_plan_id=plan.id,
        symbol="US.AAPL",
        side="BUY",
        qty=100,
        limit_price=180,
        status="SUBMITTED",
    )
    session.add_all([position, order])
    session.commit()

    assert positions_payload(session)[0]["entry_price"] == 180
    assert positions_payload(session)[0]["created_at"]
    assert positions_payload(session)[0]["shares"] == 100
    assert orders_payload(session)[0]["limit_price"] == 180


def test_terminal_api_exposes_no_real_trade_mutation_route():
    unsafe_paths = {
        "/api/order",
        "/api/cancel-order",
        "/api/real-trade",
    }
    registered = {
        (route.path, method)
        for route in app.routes
        for method in getattr(route, "methods", set())
    }

    assert all((path, "POST") not in registered for path in unsafe_paths)


def test_kline_payload_returns_chronological_valid_bars(session):
    session.add_all([
        KLine(
            symbol="US.AAPL",
            timeframe="60m",
            ts=datetime(2026, 6, 12, 14, 30),
            open=180,
            high=182,
            low=179,
            close=181,
            volume=1000,
        ),
        KLine(
            symbol="US.AAPL",
            timeframe="60m",
            ts=datetime(2026, 6, 12, 15, 30),
            open=181,
            high=183,
            low=180,
            close=182,
            volume=0,
            data_ok=False,
            anomaly_reason="zero volume",
        ),
        KLine(
            symbol="US.AAPL",
            timeframe="60m",
            ts=datetime(2026, 6, 12, 16, 30),
            open=182,
            high=184,
            low=181,
            close=183,
            volume=1200,
        ),
    ])
    session.commit()

    payload = kline_payload(session, "us.aapl", "60M", limit=300)

    assert [bar["close"] for bar in payload["bars"]] == [181, 183]
    assert payload["bars"][0]["time"] < payload["bars"][1]["time"]
    assert payload["anomaly_count"] == 1


def test_kline_payload_is_empty_safe_and_rejects_unsupported_timeframe(session):
    for timeframe in ("1m", "5m", "15m", "60m", "1d"):
        assert kline_payload(session, "US.AAPL", timeframe)["bars"] == []
    try:
        kline_payload(session, "US.AAPL", "30m")
    except ValueError as exc:
        assert "仅支持 1m、5m、15m、60m 和 1d" in str(exc)
    else:
        raise AssertionError("unsupported timeframe must be rejected")


def test_trade_plan_overlay_contains_plan_prices_without_formatting(session):
    plan = _plan()
    session.add(plan)
    session.commit()

    payload = trade_plan_overlay_payload(session, "us.aapl", plan.id)

    assert payload["plan_id"] == plan.id
    assert {line["type"] for line in payload["lines"]} == {
        "ENTRY", "NO_CHASE", "STOP", "TARGET_1", "TARGET_2", "CURRENT",
    }
    assert next(line for line in payload["lines"] if line["type"] == "ENTRY")["price"] == 180


def test_structures_payload_links_battle_item_and_trade_plan(session):
    event = StructureEvent(
        symbol="US.AAPL",
        timeframe="60m",
        event_type="BOTTOM_STRUCTURE",
        event_ts=datetime(2026, 6, 12, 14, 30),
        price=180,
        reason="底结构确认。",
    )
    session.add(event)
    session.flush()
    battle = BattlePoolItem(
        symbol="US.AAPL",
        direction="LONG",
        priority_level="S",
        source_structure_id=event.id,
        daily_state="DAILY_STRONG_BULL",
        structure_type="BOTTOM_STRUCTURE",
        score=92,
        reason="结构清晰。",
        status="ACTIVE",
    )
    session.add(battle)
    session.flush()
    plan = _plan()
    plan.source_structure_id = event.id
    plan.battle_pool_id = battle.id
    session.add(plan)
    session.commit()

    payload = structures_payload(session, "US.AAPL", "60m")

    assert payload[0]["display_name"] == "底结构"
    assert payload[0]["linked_battle_item_id"] == battle.id
    assert payload[0]["linked_trade_plan_id"] == plan.id
