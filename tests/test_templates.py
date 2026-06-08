from fastapi.testclient import TestClient

from app.db import init_db
from app.main import app


def test_dashboard_renders_chinese_labels_without_key_internal_tags():
    init_db()
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "结构趋势交易闭环" in response.text
    assert "风险偏好" in response.text or "市场状态尚未计算" in response.text or "未计算" in response.text
    assert "SCRIPT_A_BOTTOM_TREND_RESUME" not in response.text
    assert ">ENTRY_CANDIDATE<" not in response.text
    assert ">BOTTOM_STRUCTURE<" not in response.text


def test_risk_page_groups_settings_in_chinese():
    init_db()
    client = TestClient(app)
    response = client.get("/risk")
    assert response.status_code == 200
    assert "账户风险" in response.text
    assert "剧本调整" in response.text
    assert "仓位限制" in response.text
    assert "冷却机制" in response.text
