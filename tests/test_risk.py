from app.models import RiskConfig
from app.services.risk import calculate_position_size


def test_no_stop_means_no_entry_position_size():
    config = RiskConfig(account_equity=100000, risk_per_trade_pct=0.01, max_symbol_position_pct=0.2)
    assert calculate_position_size(config, entry_price=100, stop_price=None, market_state="RISK_ON", script="SCRIPT_A_BOTTOM_TREND_RESUME") is None
    assert calculate_position_size(config, entry_price=100, stop_price=101, market_state="RISK_ON", script="SCRIPT_A_BOTTOM_TREND_RESUME") is None


def test_script_b_uses_lower_risk():
    config = RiskConfig(account_equity=100000, risk_per_trade_pct=0.01, script_b_risk_multiplier=0.5, max_symbol_position_pct=1)
    a = calculate_position_size(config, 100, 95, "RISK_ON", "SCRIPT_A_BOTTOM_TREND_RESUME")
    b = calculate_position_size(config, 100, 95, "RISK_ON", "SCRIPT_B_TOP_INVALIDATION_CONTINUATION")
    assert a is not None
    assert b is not None
    assert b.allowed_loss == a.allowed_loss * 0.5
    assert b.shares == a.shares // 2

