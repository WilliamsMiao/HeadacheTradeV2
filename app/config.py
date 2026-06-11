from functools import lru_cache

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:  # pragma: no cover
    from pydantic import BaseSettings
    SettingsConfigDict = dict


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "sqlite:///./data/headache_trade.sqlite3"
    futu_host: str = "127.0.0.1"
    futu_port: int = 11111
    futu_market: str = "US"
    futu_watchlist_group: str = ""
    futu_include_5m: bool = False
    market_filter_symbols: str = "SPY,QQQ"
    public_base_url: str = "http://127.0.0.1:8001"
    enable_sim_trading: bool = True
    enable_real_trading: bool = False
    enable_auto_approval: bool = True
    enable_auto_short: bool = False
    sim_trade_market: str = "US"
    sim_trade_security_firm: str = "FUTUSECURITIES"
    max_positions: int = 1
    risk_per_trade_pct: float = 0.005
    max_symbol_position_pct: float = 0.4
    max_spread_pct: float = 0.002
    max_daily_new_trades: int = 3
    max_daily_loss_pct: float = 0.015
    max_consecutive_losses: int = 3
    entry_order_timeout_seconds: int = 60
    force_intraday_exit: bool = True
    enable_overnight_hold: bool = False
    no_new_entry_before_minutes_after_open: int = 60
    no_new_entry_before_close_minutes: int = 30
    max_realtime_subscriptions: int = 30
    max_orderbook_subscriptions: int = 10
    max_ticker_subscriptions: int = 10

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def market_symbols(self) -> list[str]:
        return [item.strip().upper() for item in self.market_filter_symbols.split(",") if item.strip()]

    def assert_simulation_only(self) -> None:
        if self.enable_real_trading:
            raise RuntimeError("Real trading is disabled in this version")


@lru_cache
def get_settings() -> Settings:
    return Settings()
