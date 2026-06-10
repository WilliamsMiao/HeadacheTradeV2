from fastapi.testclient import TestClient
from sqlalchemy import delete
from datetime import date, datetime

from app.db import init_db
from app.db import SessionLocal
from app.main import _dashboard_context, app
from app.models import MarketState, SystemConfig


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
    assert "结构趋势交易闭环" in response.text
    assert "风险偏好" in response.text or "市场状态尚未计算" in response.text or "未计算" in response.text
    assert "SCRIPT_A_BOTTOM_TREND_RESUME" not in response.text
    assert ">ENTRY_CANDIDATE<" not in response.text
    assert ">BOTTOM_STRUCTURE<" not in response.text
    assert "/static/styles.css?v=" in response.text
    assert "/static/app.js?v=" in response.text


def test_risk_page_groups_settings_in_chinese():
    client = authenticated_client()
    response = client.get("/risk")
    assert response.status_code == 200
    assert "账户风险" in response.text
    assert "剧本调整" in response.text
    assert "仓位限制" in response.text
    assert "冷却机制" in response.text


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
