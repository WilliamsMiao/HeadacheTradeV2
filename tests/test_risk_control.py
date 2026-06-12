from app.config import Settings
from app.models import AuditLog
from app.services.risk_control import effective_risk_settings, update_risk_settings


def values():
    return {
        "risk_per_trade_pct": 0.005,
        "max_positions": 2,
        "max_symbol_position_pct": 0.4,
        "max_daily_new_trades": 3,
        "max_daily_loss_pct": 0.015,
        "max_consecutive_losses": 3,
        "force_intraday_exit": True,
        "enable_overnight_hold": False,
        "no_new_entry_before_minutes_after_open": 60,
        "no_new_entry_before_close_minutes": 30,
    }


def test_runtime_risk_values_are_effective_and_audited(session):
    update_risk_settings(session, Settings(max_positions=1), values(), "观察期调整")

    effective = effective_risk_settings(session, Settings(max_positions=1))
    audit = session.query(AuditLog).filter(AuditLog.action == "RISK_CONFIG_UPDATED").one()

    assert effective.max_positions == 2
    assert effective.risk_per_trade_pct == 0.005
    assert audit.reason == "观察期调整"


def test_dangerous_risk_per_trade_is_rejected(session):
    payload = values()
    payload["risk_per_trade_pct"] = 0.051

    try:
        update_risk_settings(session, Settings(), payload, "")
    except ValueError as exc:
        assert "不得超过 5%" in str(exc)
    else:
        raise AssertionError("dangerous configuration must be rejected")
