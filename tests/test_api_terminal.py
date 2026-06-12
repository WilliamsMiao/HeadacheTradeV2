from datetime import UTC, datetime

from app.main import app
from app.config import Settings
from app.models import (
    BattlePoolItem,
    CandidateStock,
    KLine,
    Position,
    SimOrder,
    StructureEvent,
    SystemConfig,
    TradePlan,
)
from app.services.terminal_api import (
    kline_payload,
    orders_payload,
    positions_payload,
    terminal_summary,
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


def test_trade_plan_list_orders_s_before_a_and_exposes_display_state(session):
    session.add_all([_plan("US.MSFT", "A"), _plan("US.AAPL", "S")])
    session.commit()

    plans = trade_plan_list(session, Settings(), priority="S,A")

    assert [plan["priority_level"] for plan in plans] == ["S", "A"]
    assert plans[0]["display_status"]["display_name"] == "持续监控中"
    assert plans[0]["next_system_action"]
    assert plans[0]["checks"]


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
    assert kline_payload(session, "US.AAPL", "1d")["bars"] == []
    try:
        kline_payload(session, "US.AAPL", "5m")
    except ValueError as exc:
        assert "仅支持 60m 和 1d" in str(exc)
    else:
        raise AssertionError("unsupported timeframe must be rejected")
