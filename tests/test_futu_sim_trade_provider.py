import inspect

import pytest

from app.config import Settings
from app.providers.futu_trade_provider import FutuTradeProvider


def test_real_trading_is_always_rejected():
    with pytest.raises(RuntimeError, match="Real trading is disabled"):
        FutuTradeProvider(Settings(enable_real_trading=True))


def test_order_implementation_hardcodes_simulate_environment():
    source = inspect.getsource(FutuTradeProvider.place_simulated_order)
    assert "TrdEnv.SIMULATE" in source
    assert "TrdEnv.REAL" not in source
    assert "trd_env" not in inspect.signature(FutuTradeProvider.place_simulated_order).parameters
