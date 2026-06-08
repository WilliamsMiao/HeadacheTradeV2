from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db import SessionLocal, init_db
from app.main import app
from app.models import SystemConfig


def reset_auth() -> None:
    init_db()
    with SessionLocal() as session:
        session.execute(delete(SystemConfig))
        session.commit()


def test_first_visit_redirects_to_password_setup():
    reset_auth()
    client = TestClient(app)
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/setup-password"


def test_setup_login_and_reject_wrong_password():
    reset_auth()
    client = TestClient(app)
    setup = client.post("/api/auth/setup-password", json={"password": "local-test-password"})
    assert setup.status_code == 200
    assert client.get("/").status_code == 200

    client.post("/api/auth/logout")
    denied = client.post("/api/auth/login", json={"password": "wrong-password"})
    assert denied.status_code == 401
    accepted = client.post("/api/auth/login", json={"password": "local-test-password"})
    assert accepted.status_code == 200


def test_api_requires_login_after_password_is_configured():
    reset_auth()
    client = TestClient(app)
    client.post("/api/auth/setup-password", json={"password": "local-test-password"})
    client.post("/api/auth/logout")
    response = client.post("/tasks/run-pipeline")
    assert response.status_code == 401
    assert response.json()["detail"] == "请先登录"
