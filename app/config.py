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
    market_filter_symbols: str = "SPY,QQQ"
    public_base_url: str = "http://127.0.0.1:8001"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def market_symbols(self) -> list[str]:
        return [item.strip().upper() for item in self.market_filter_symbols.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

