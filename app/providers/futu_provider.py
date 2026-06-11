from datetime import datetime
from time import monotonic, sleep

from app.config import Settings
from app.domain import Bar, DAILY, HOUR_60, MIN_15, MIN_5
from app.providers.base import MarketDataProvider


class FutuProvider(MarketDataProvider):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._quote_ctx = None
        self._last_history_request_at = 0.0

    def _quote_context(self):
        if self._quote_ctx is not None:
            return self._quote_ctx
        try:
            from futu import OpenQuoteContext
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("futu-api is not installed. Install with: pip install -e '.[futu]'") from exc
        self._quote_ctx = OpenQuoteContext(host=self.settings.futu_host, port=self.settings.futu_port)
        return self._quote_ctx

    def close(self) -> None:
        if self._quote_ctx is not None:
            self._quote_ctx.close()
            self._quote_ctx = None

    def get_watchlist(self) -> list[dict[str, str]]:
        quote_ctx = self._quote_context()
        group_name = self.settings.futu_watchlist_group or self._discover_watchlist_group(quote_ctx)
        ret, data = quote_ctx.get_user_security(group_name)
        if ret != 0:
            raise RuntimeError(f"Futu get_user_security failed: {data}")
        rows = data.to_dict("records")
        output = []
        for row in rows:
            raw_code = str(row.get("code") or row.get("symbol") or "").upper()
            if not raw_code.startswith("US."):
                continue
            code = raw_code.replace("US.", "")
            if not code or code.startswith("."):
                continue
            output.append(
                {
                    "symbol": code,
                    "name": str(row.get("name") or code),
                    "industry": str(row.get("industry") or ""),
                    "source_group": group_name,
                }
            )
        return output

    def _discover_watchlist_group(self, quote_ctx) -> str:
        ret, data = quote_ctx.get_user_security_group()
        if ret != 0:
            raise RuntimeError(f"Futu get_user_security_group failed: {data}")
        rows = data.to_dict("records")
        if not rows:
            raise RuntimeError("Futu has no watchlist groups")
        preferred = ["美股", "US", "自选股", "全部"]
        for name in preferred:
            for row in rows:
                group_name = str(row.get("group_name") or "")
                if name.lower() in group_name.lower():
                    return group_name
        return str(rows[0]["group_name"])

    def get_klines(
        self,
        symbol: str,
        timeframe: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Bar]:
        quote_ctx = self._quote_context()
        from futu import KLType

        futu_symbol = symbol if symbol.startswith("US.") else f"US.{symbol}"
        ktype = self._kline_type(KLType, timeframe)
        start_s = start.strftime("%Y-%m-%d") if start else None
        end_s = end.strftime("%Y-%m-%d") if end else None
        self._wait_for_history_quota()
        ret, data, _ = quote_ctx.request_history_kline(
            futu_symbol,
            start=start_s,
            end=end_s,
            ktype=ktype,
            max_count=None,
        )
        if ret != 0:
            raise RuntimeError(f"Futu request_history_kline failed for {symbol} {timeframe}: {data}")
        bars = []
        for row in data.to_dict("records"):
            ts_raw = row.get("time_key") or row.get("date")
            ts = datetime.strptime(str(ts_raw), "%Y-%m-%d %H:%M:%S") if " " in str(ts_raw) else datetime.strptime(str(ts_raw), "%Y-%m-%d")
            bars.append(
                Bar(
                    symbol=symbol.upper(),
                    timeframe=timeframe,
                    ts=ts,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row.get("volume", 0)),
                )
            )
        return bars

    @staticmethod
    def _kline_type(kl_type, timeframe: str):
        mapping = {
            DAILY: kl_type.K_DAY,
            HOUR_60: kl_type.K_60M,
            MIN_15: kl_type.K_15M,
            MIN_5: kl_type.K_5M,
        }
        try:
            return mapping[timeframe]
        except KeyError as exc:
            raise ValueError(f"unsupported Futu timeframe: {timeframe}") from exc

    def _wait_for_history_quota(self) -> None:
        elapsed = monotonic() - self._last_history_request_at
        if elapsed < 0.55:
            sleep(0.55 - elapsed)
        self._last_history_request_at = monotonic()
