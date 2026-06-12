from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db import SessionLocal, init_db
from app.main import app
from app.models import SystemConfig
from app.services import opend_admin


def authenticated_client() -> TestClient:
    init_db()
    with SessionLocal() as session:
        session.execute(delete(SystemConfig))
        session.commit()
    client = TestClient(app)
    assert client.post("/api/auth/setup-password", json={"password": "local-test-password"}).status_code == 200
    return client


def test_opend_status_api_masks_sensitive_workflow(monkeypatch):
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
                "credentials_configured": True,
                "needs_phone_code": False,
                "needs_captcha_code": False,
                "recent_log": "OpenD started",
            },
        ),
    )
    monkeypatch.setattr(opend_admin, "opend_socket_health", lambda: (_ for _ in ()).throw(AssertionError("duplicate probe")))
    client = authenticated_client()
    response = client.get("/api/opend/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["credentials_configured"] is True
    assert payload["socket_health"]["connected"] is True
    assert "password" not in response.text.lower()


def test_opend_diagnostics_is_loaded_on_demand(monkeypatch):
    calls = []

    def fake_diagnostics() -> opend_admin.AdminResult:
        calls.append("diagnostics")
        return opend_admin.AdminResult(
            True,
            "诊断日志已读取",
            {"api_port_open": True, "recent_log": "bounded diagnostic log"},
        )

    monkeypatch.setattr(opend_admin, "diagnostics", fake_diagnostics)
    client = authenticated_client()
    response = client.get("/api/opend/diagnostics")
    assert response.status_code == 200
    assert response.json()["recent_log"] == "bounded diagnostic log"
    assert calls == ["diagnostics"]


def test_opend_verify_code_supports_phone_and_captcha(monkeypatch):
    calls = []

    def fake_verify(kind: str, code: str) -> opend_admin.AdminResult:
        calls.append((kind, code))
        return opend_admin.AdminResult(True, "验证码已提交", {"telnet_reply": "ok"})

    monkeypatch.setattr(opend_admin, "verify_code", fake_verify)
    monkeypatch.setattr(
        opend_admin,
        "opend_socket_health",
        lambda: {"status": "ok", "host": "127.0.0.1", "port": 11111, "connected": True},
    )
    client = authenticated_client()
    assert client.post("/api/opend/verify-code", json={"kind": "phone", "code": "123456"}).status_code == 200
    assert client.post("/api/opend/verify-code", json={"kind": "captcha", "code": "abcd"}).status_code == 200
    assert calls == [("phone", "123456"), ("captcha", "abcd")]
