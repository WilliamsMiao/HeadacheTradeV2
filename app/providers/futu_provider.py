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
        self._stock_filter_requests: list[float] = []

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

    def get_stock_filter_candidates(self) -> list[dict[str, object]]:
        from futu import (
            AccumulateFilter,
            KLType,
            Market,
            PatternFilter,
            SimpleFilter,
            SortDir,
            StockField,
        )

        quote_ctx = self._quote_context()
        pattern_groups = {
            "LOW_REBOUND": (
                ("MACD_LOW_IMPROVING", StockField.MACD_GOLD_CROSS_LOW),
                ("KDJ_LOW_GOLD_CROSS", StockField.KDJ_GOLD_CROSS_LOW),
                ("KDJ_BOTTOM_DIVERGENCE", StockField.KDJ_BOTTOM_DIVERGENCE),
                ("BOLL_CROSS_MIDDLE_UP", StockField.BOLL_CROSS_MIDDLE_UP),
            ),
            "TREND_UP": (
                ("MA_ALIGNMENT_LONG", StockField.MA_ALIGNMENT_LONG),
                ("EMA_ALIGNMENT_LONG", StockField.EMA_ALIGNMENT_LONG),
                ("BOLL_BREAK_UPPER", StockField.BOLL_BREAK_UPPER),
                ("BOLL_CROSS_MIDDLE_UP", StockField.BOLL_CROSS_MIDDLE_UP),
            ),
            "HIGH_RISK": (
                ("MACD_DEATH_CROSS_HIGH", StockField.MACD_DEATH_CROSS_HIGH),
                ("MACD_TOP_DIVERGENCE", StockField.MACD_TOP_DIVERGENCE),
                ("KDJ_DEATH_CROSS_HIGH", StockField.KDJ_DEATH_CROSS_HIGH),
                ("RSI_TOP_DIVERGENCE", StockField.RSI_TOP_DIVERGENCE),
            ),
            "WEAK_DOWN": (
                ("MA_ALIGNMENT_SHORT", StockField.MA_ALIGNMENT_SHORT),
                ("EMA_ALIGNMENT_SHORT", StockField.EMA_ALIGNMENT_SHORT),
                ("BOLL_CROSS_MIDDLE_DOWN", StockField.BOLL_CROSS_MIDDLE_DOWN),
            ),
        }
        output: list[dict[str, object]] = []
        for pool_type, patterns in pattern_groups.items():
            for tag, stock_field in patterns:
                price_filter = SimpleFilter()
                price_filter.stock_field = StockField.CUR_PRICE
                price_filter.filter_min = 5
                price_filter.is_no_filter = False

                market_value_filter = SimpleFilter()
                market_value_filter.stock_field = StockField.MARKET_VAL
                market_value_filter.filter_min = 2_000_000_000
                market_value_filter.is_no_filter = False

                volume_ratio = SimpleFilter()
                volume_ratio.stock_field = StockField.VOLUME_RATIO
                volume_ratio.is_no_filter = True

                turnover_filter = AccumulateFilter()
                turnover_filter.stock_field = StockField.TURNOVER
                turnover_filter.days = 3
                turnover_filter.filter_min = 20_000_000
                turnover_filter.sort = SortDir.DESCEND
                turnover_filter.is_no_filter = False

                pattern_filter = PatternFilter()
                pattern_filter.stock_field = stock_field
                pattern_filter.ktype = KLType.K_DAY
                pattern_filter.is_no_filter = False

                filters = [
                    price_filter,
                    market_value_filter,
                    volume_ratio,
                    turnover_filter,
                    pattern_filter,
                ]
                begin = 0
                while begin < 300:
                    self._wait_for_stock_filter_quota()
                    ret, data = self._request_stock_filter(
                        quote_ctx,
                        Market.US,
                        filters,
                        begin,
                        min(200, 300 - begin),
                    )
                    if ret != 0:
                        raise RuntimeError(f"Futu get_stock_filter failed for {pool_type}/{tag}: {data}")
                    last_page, _, rows = data
                    for row in rows:
                        code = str(row.stock_code or "").upper()
                        if not code.startswith("US.") or code.startswith("US.."):
                            continue
                        output.append(
                            {
                                "symbol": code.removeprefix("US."),
                                "name": str(row.stock_name or code.removeprefix("US.")),
                                "market": "US",
                                "pool_type": pool_type,
                                "tag": tag,
                                "cur_price": _futu_value(row, price_filter),
                                "market_val": _futu_value(row, market_value_filter),
                                "turnover_3d": _futu_value(row, turnover_filter),
                                "volume_ratio": _futu_value(row, volume_ratio),
                            }
                        )
                    if last_page or not rows:
                        break
                    begin += len(rows)
        return output

    def get_market_snapshot(self, symbols: list[str]) -> list[dict[str, object]]:
        quote_ctx = self._quote_context()
        codes = [symbol if symbol.startswith("US.") else f"US.{symbol}" for symbol in symbols]
        ret, data = quote_ctx.get_market_snapshot(codes)
        if ret != 0:
            raise RuntimeError(f"Futu get_market_snapshot failed: {data}")
        return data.to_dict("records")

    def set_price_reminder(
        self,
        symbol: str,
        reminder_type: str,
        value: float,
        note: str,
    ) -> int:
        from futu import PriceReminderFreq, PriceReminderType, SetPriceReminderOp

        type_map = {
            "PRICE_UP": PriceReminderType.PRICE_UP,
            "PRICE_DOWN": PriceReminderType.PRICE_DOWN,
        }
        if reminder_type not in type_map:
            raise ValueError(f"unsupported reminder type: {reminder_type}")
        code = symbol if symbol.startswith("US.") else f"US.{symbol}"
        ret, data = self._quote_context().set_price_reminder(
            code=code,
            op=SetPriceReminderOp.ADD,
            reminder_type=type_map[reminder_type],
            reminder_freq=PriceReminderFreq.ALWAYS,
            value=value,
            note=note[:10],
        )
        if ret != 0:
            raise RuntimeError(f"Futu set_price_reminder failed for {symbol}: {data}")
        return int(data)

    def get_price_reminders(self, symbol: str) -> list[dict[str, object]]:
        code = symbol if symbol.startswith("US.") else f"US.{symbol}"
        ret, data = self._quote_context().get_price_reminder(code=code)
        if ret != 0:
            if "empty data" in str(data).lower():
                return []
            raise RuntimeError(f"Futu get_price_reminder failed for {symbol}: {data}")
        return data.to_dict("records")

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
                    turnover=float(row.get("turnover", 0) or 0),
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

    def _wait_for_stock_filter_quota(self) -> None:
        now = monotonic()
        self._stock_filter_requests = [
            timestamp for timestamp in self._stock_filter_requests
            if now - timestamp < 30.0
        ]
        if len(self._stock_filter_requests) >= 10:
            wait_seconds = 30.2 - (now - self._stock_filter_requests[0])
            if wait_seconds > 0:
                sleep(wait_seconds)
        self._stock_filter_requests.append(monotonic())

    @staticmethod
    def _request_stock_filter(quote_ctx, market, filters, begin: int, num: int):
        ret, data = quote_ctx.get_stock_filter(
            market=market,
            filter_list=filters,
            begin=begin,
            num=num,
        )
        if ret != 0 and "每30秒最多10次" in str(data):
            sleep(30.2)
            ret, data = quote_ctx.get_stock_filter(
                market=market,
                filter_list=filters,
                begin=begin,
                num=num,
            )
        return ret, data


def _futu_value(row, filter_item) -> float | None:
    try:
        value = row[filter_item]
        return float(value)
    except (KeyError, TypeError, ValueError):
        return None
