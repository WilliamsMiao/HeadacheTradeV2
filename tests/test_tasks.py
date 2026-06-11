from datetime import datetime
from time import sleep

from fastapi.testclient import TestClient
from sqlalchemy import delete

from app import main
from app.auth import setup_password
from app.db import SessionLocal, init_db
from app.domain import Bar
from app.main import app
from app.models import SystemConfig
from app.providers.base import MarketDataProvider
from app.services.data_ingestion import update_market_data
from app.services.task_runner import TaskState, get_task, start_task


class ProgressProvider(MarketDataProvider):
    def get_watchlist(self):
        return []

    def get_klines(self, symbol, timeframe, start=None, end=None):
        return [Bar(symbol, timeframe, datetime(2026, 6, 10), 10, 11, 9, 10.5, 100)]


def authenticated_client() -> TestClient:
    init_db()
    with SessionLocal() as session:
        session.execute(delete(SystemConfig))
        session.commit()
        setup_password(session, "local-test-password")
    client = TestClient(app)
    response = client.post("/api/auth/login", json={"password": "local-test-password"})
    assert response.status_code == 200
    return client


def test_market_data_reports_progress_per_symbol_and_timeframe(session):
    updates = []

    update_market_data(
        session,
        ProgressProvider(),
        ["AAPL", "MSFT"],
        on_progress=lambda current, total, message: updates.append((current, total, message)),
    )

    assert len(updates) == 4
    assert updates[0] == (1, 4, "正在更新 AAPL · 1d")
    assert updates[-1] == (4, 4, "正在更新 MSFT · 60m")


def test_task_runner_records_success_and_progress():
    state = start_task(
        "test-task",
        lambda progress: (progress(1, 2, "第一步"), progress(2, 2, "第二步"), {"updated": 2})[-1],
    )

    for _ in range(50):
        current = get_task(state.id)
        if current and current.status == "SUCCEEDED":
            break
        sleep(0.01)

    assert current is not None
    assert current.status == "SUCCEEDED"
    assert current.current == 2
    assert current.total == 2
    assert current.result == {"updated": 2}


def test_long_task_endpoint_returns_accepted_immediately(monkeypatch):
    client = authenticated_client()
    state = TaskState(id="task-123", name="update-market-data")
    monkeypatch.setattr(main, "start_task", lambda name, function: state)

    response = client.post("/tasks/update-market-data")

    assert response.status_code == 202
    assert response.json()["id"] == "task-123"
    assert response.json()["status"] == "PENDING"


def test_long_task_endpoint_rejects_concurrent_task(monkeypatch):
    client = authenticated_client()

    def reject_start(name, function):
        raise RuntimeError("任务“更新行情”正在执行，请等待完成")

    monkeypatch.setattr(main, "start_task", reject_start)
    response = client.post("/tasks/update-market-data")

    assert response.status_code == 409
    assert "正在执行" in response.json()["detail"]
