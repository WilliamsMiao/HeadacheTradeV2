from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from datetime import date, datetime

from app.db import init_db
from app.db import SessionLocal
from app.main import _dashboard_context, app
from app.models import (
    BattlePoolItem,
    CandidateStock,
    MarketState,
    StructureEvent,
    SystemConfig,
    TradePlan,
    TradeSignal,
    WatchlistItem,
)


def authenticated_client() -> TestClient:
    init_db()
    with SessionLocal() as session:
        session.execute(delete(SystemConfig))
        session.commit()
    client = TestClient(app)
    response = client.post("/api/auth/setup-password", json={"password": "local-test-password"})
    assert response.status_code == 200
    return client


def test_dashboard_renders_chinese_labels_without_key_internal_tags():
    client = authenticated_client()
    response = client.get("/")
    assert response.status_code == 200
    assert "日线 + 60 分钟结构监控" in response.text
    assert "风险偏好" in response.text or "市场状态尚未计算" in response.text or "未计算" in response.text
    assert "SCRIPT_A_BOTTOM_TREND_RESUME" not in response.text
    assert ">ENTRY_CANDIDATE<" not in response.text
    assert ">BOTTOM_STRUCTURE<" not in response.text
    assert "/static/styles.css?v=" in response.text
    assert "/static/app.js?v=" in response.text
    assert "data-task-progress" in response.text


def test_risk_page_groups_settings_in_chinese():
    client = authenticated_client()
    response = client.get("/risk")
    assert response.status_code == 200
    assert "账户风险" in response.text
    assert "剧本调整" in response.text
    assert "仓位限制" in response.text
    assert "冷却机制" in response.text


def test_structures_page_defaults_to_active_candidates_and_keeps_history_separate():
    client = authenticated_client()
    now = datetime(2026, 6, 11, 10, 0)
    with SessionLocal() as session:
        session.execute(delete(StructureEvent))
        session.execute(delete(CandidateStock))
        session.add_all(
            [
                CandidateStock(
                    symbol="US.ACTIVE",
                    name="Active",
                    pool_type="TREND_UP",
                    active=True,
                    selected_at=now,
                ),
                CandidateStock(
                    symbol="US.LEGACY",
                    name="Legacy",
                    pool_type="TREND_UP",
                    active=False,
                    selected_at=now,
                ),
                StructureEvent(
                    symbol="US.ACTIVE",
                    timeframe="60m",
                    event_type="BOTTOM_STRUCTURE",
                    event_ts=now,
                    price=100,
                    reason="active event",
                ),
                StructureEvent(
                    symbol="US.LEGACY",
                    timeframe="60m",
                    event_type="TOP_STRUCTURE",
                    event_ts=now,
                    price=90,
                    reason="legacy event",
                ),
            ]
        )
        session.commit()

    active_response = client.get("/structures")
    history_response = client.get("/structures?scope=history")

    assert active_response.status_code == 200
    assert "当前候选结构" in active_response.text
    assert "US.ACTIVE" in active_response.text
    assert "US.LEGACY" not in active_response.text
    assert history_response.status_code == 200
    assert "全部历史结构" in history_response.text
    assert "US.ACTIVE" in history_response.text
    assert "US.LEGACY" in history_response.text


def test_opend_page_requires_auth_then_renders(monkeypatch):
    from app.services import opend_admin

    monkeypatch.setattr(
        opend_admin,
        "status",
        lambda: opend_admin.AdminResult(
            True,
            "状态已刷新",
            {
                "installed": True,
                "service_active": "active",
                "service_enabled": "enabled",
                "api_port_open": True,
                "telnet_port_open": True,
                "credentials_configured": False,
                "needs_phone_code": True,
                "needs_captcha_code": False,
                "recent_log": "需要手机验证码",
            },
        ),
    )
    monkeypatch.setattr(
        opend_admin,
        "opend_socket_health",
        lambda: {"status": "ok", "host": "127.0.0.1", "port": 11111, "connected": True},
    )
    init_db()
    with SessionLocal() as session:
        session.execute(delete(SystemConfig))
        session.commit()
    anonymous = TestClient(app)
    assert anonymous.get("/opend", follow_redirects=False).status_code == 303
    client = authenticated_client()
    response = client.get("/opend")
    assert response.status_code == 200
    assert "Futu OpenD 管理" in response.text
    assert "手机验证码" in response.text


def test_dashboard_uses_most_recently_computed_market_state(session):
    session.add_all(
        [
            MarketState(
                as_of=date(2026, 6, 10),
                state="RISK_OFF",
                reason="SPY market data or indicators missing",
                updated_at=datetime(2026, 6, 10, 9, 0),
            ),
            MarketState(
                as_of=date(2026, 6, 9),
                state="RISK_ON",
                reason="SPY: close > MA60; QQQ: close > MA60",
                updated_at=datetime(2026, 6, 10, 10, 0),
            ),
        ]
    )
    session.commit()

    assert _dashboard_context(session)["market"].state == "RISK_ON"


def test_dashboard_trade_plans_put_s_level_before_a_level(session):
    for index in range(7):
        session.add(
            TradePlan(
                symbol=f"A{index}",
                source_structure_id=100 + index,
                battle_pool_id=100 + index,
                structure_type="BOTTOM_STRUCTURE",
                priority_level="A",
                stop_price=90,
                target_1=110,
                target_2=120,
                trailing_rule="trail",
                time_stop_rule="time",
                invalid_condition="invalid",
                risk_reward_1=1.5,
                risk_reward_2=2,
                reason="A plan",
                status="ACTIVE",
            )
        )
    session.add(
        TradePlan(
            symbol="S_TOP",
            source_structure_id=999,
            battle_pool_id=999,
            structure_type="BOTTOM_STRUCTURE",
            priority_level="S",
            stop_price=90,
            target_1=110,
            target_2=120,
            trailing_rule="trail",
            time_stop_rule="time",
            invalid_condition="invalid",
            risk_reward_1=1.5,
            risk_reward_2=2,
            reason="S plan",
            status="ACTIVE",
        )
    )
    session.commit()

    plans = _dashboard_context(session)["plans"]
    assert len(plans) == 6
    assert plans[0].symbol == "S_TOP"
    assert plans[0].priority_level == "S"


def test_trade_plan_page_renders_entry_stop_targets_and_rules():
    client = authenticated_client()
    with SessionLocal() as session:
        session.execute(delete(TradePlan))
        session.execute(delete(BattlePoolItem).where(BattlePoolItem.symbol == "AAPL"))
        battle = BattlePoolItem(
            symbol="AAPL", direction="LONG", priority_level="S", source_structure_id=12,
            daily_state="DAILY_STRONG_BULL", structure_type="BOTTOM_STRUCTURE",
            score=92, reason="test", status="ACTIVE",
        )
        session.add(battle)
        session.flush()
        session.add(TradePlan(
            symbol="AAPL", name="Apple", direction="LONG", source_structure_id=12,
            battle_pool_id=battle.id, daily_state="DAILY_STRONG_BULL",
            structure_type="BOTTOM_STRUCTURE", priority_level="S",
            entry_mode="BREAKOUT_OR_PULLBACK", breakout_entry_price=102.5,
            pullback_entry_low=101.5, pullback_entry_high=102,
            low_absorb_entry_low=98, low_absorb_entry_high=99,
            stop_price=95, target_1=113.75, target_2=117.5,
            trailing_rule="达到 1R 后抬高止损", time_stop_rule="3 根 K 未走强失效",
            invalid_condition="跌破结构低点", risk_reward_1=1.5, risk_reward_2=2,
            status="ACTIVE", reason="人工复核计划",
        ))
        session.commit()

    response = client.get("/trade-plans")
    with SessionLocal() as session:
        session.execute(delete(TradePlan))
        session.execute(delete(BattlePoolItem))
        session.commit()

    assert response.status_code == 200
    assert "关键触发价" in response.text
    assert "硬止损" in response.text
    assert "第一目标" in response.text
    assert "移动止盈" in response.text


def test_symbol_detail_renders_cancelled_signal_reason():
    client = authenticated_client()
    with SessionLocal() as session:
        session.execute(delete(TradeSignal))
        item = session.scalar(select(WatchlistItem).where(WatchlistItem.symbol == "AAPL"))
        if item is None:
            session.add(WatchlistItem(symbol="AAPL", name="Apple", active=True))
        session.add(
            TradeSignal(
                symbol="AAPL",
                signal_type="ENTRY",
                status="CANCELLED_BY_TRIGGER",
                action="入场候选",
                source_structure_id=12,
                trigger_timeframe="15m",
                trigger_ts=datetime(2026, 6, 8, 11, 15),
                trigger_level=101.8,
                reason="original entry",
                cancel_reason="15 分钟触发后跌回触发位下方",
            )
        )
        session.commit()

    response = client.get("/symbols/AAPL")
    with SessionLocal() as session:
        session.execute(delete(TradeSignal))
        session.commit()

    assert response.status_code == 200
    assert "建议与纠错历史" in response.text
    assert "因触发失败取消" in response.text
    assert "15 分钟触发后跌回触发位下方" in response.text


def test_workbench_page_and_apis_render_without_exposing_internal_labels():
    client = authenticated_client()
    with SessionLocal() as session:
        item = session.scalar(select(WatchlistItem).where(WatchlistItem.symbol == "AAPL"))
        if item is None:
            session.add(WatchlistItem(symbol="AAPL", name="Apple", active=True))
            session.commit()

    response = client.get("/workbench/AAPL")
    assert response.status_code == 200
    assert "多周期决策工作台" in response.text
    assert "前端不生成独立信号" in response.text
    assert ">WAIT_15M_TRIGGER<" not in response.text

    for endpoint in ("frames", "state", "events", "signals", "debug"):
        api_response = client.get(f"/api/workbench/AAPL/{endpoint}")
        assert api_response.status_code == 200
        assert api_response.json()["symbol"] == "AAPL"


def test_simulation_pages_render_and_require_auth():
    client = authenticated_client()
    for path, heading in (
        ("/sim-orders", "模拟订单"),
        ("/positions", "模拟持仓"),
        ("/journal", "交易日志"),
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert heading in response.text
