from __future__ import annotations

from typing import Any

from app.config import Settings


class FutuTradeProvider:
    def __init__(self, settings: Settings) -> None:
        settings.assert_simulation_only()
        self.settings = settings
        self._trade_ctx = None

    def _context(self):
        if self._trade_ctx is not None:
            return self._trade_ctx
        try:
            from futu import OpenSecTradeContext, SecurityFirm, TrdMarket
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("futu-api is not installed") from exc
        market = getattr(TrdMarket, self.settings.sim_trade_market, TrdMarket.US)
        security_firm = getattr(
            SecurityFirm,
            self.settings.sim_trade_security_firm,
            SecurityFirm.FUTUSECURITIES,
        )
        self._trade_ctx = OpenSecTradeContext(
            filter_trdmarket=market,
            host=self.settings.futu_host,
            port=self.settings.futu_port,
            security_firm=security_firm,
        )
        return self._trade_ctx

    def close(self) -> None:
        if self._trade_ctx is not None:
            self._trade_ctx.close()
            self._trade_ctx = None

    def get_accounts(self) -> list[dict[str, Any]]:
        from futu import TrdEnv

        ret, data = self._context().get_acc_list()
        rows = self._rows(ret, data, "get_acc_list")
        return [row for row in rows if str(row.get("trd_env")) == str(TrdEnv.SIMULATE)]

    def get_account_info(self) -> dict[str, Any]:
        from futu import TrdEnv

        ret, data = self._context().accinfo_query(trd_env=TrdEnv.SIMULATE)
        rows = self._rows(ret, data, "accinfo_query")
        return rows[0] if rows else {}

    def get_positions(self) -> list[dict[str, Any]]:
        from futu import TrdEnv

        ret, data = self._context().position_list_query(trd_env=TrdEnv.SIMULATE)
        return self._rows(ret, data, "position_list_query")

    def get_open_orders(self) -> list[dict[str, Any]]:
        from futu import TrdEnv

        ret, data = self._context().order_list_query(trd_env=TrdEnv.SIMULATE)
        return self._rows(ret, data, "order_list_query")

    def get_deals(self) -> list[dict[str, Any]]:
        from futu import TrdEnv

        ret, data = self._context().deal_list_query(trd_env=TrdEnv.SIMULATE)
        return self._rows(ret, data, "deal_list_query")

    def place_simulated_order(
        self,
        symbol: str,
        side: str,
        qty: int,
        limit_price: float,
    ) -> dict[str, Any]:
        from futu import OrderType, TrdEnv, TrdSide

        if not self.settings.enable_sim_trading:
            raise RuntimeError("Simulated trading is disabled")
        if qty <= 0 or limit_price <= 0:
            raise ValueError("qty and limit_price must be positive")
        side_value = TrdSide.BUY if side == "BUY" else TrdSide.SELL
        code = symbol if symbol.startswith("US.") else f"US.{symbol}"
        ret, data = self._context().place_order(
            price=round(limit_price, 2),
            qty=qty,
            code=code,
            trd_side=side_value,
            order_type=OrderType.NORMAL,
            trd_env=TrdEnv.SIMULATE,
        )
        rows = self._rows(ret, data, "place_order")
        return rows[0] if rows else {}

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        from futu import ModifyOrderOp, TrdEnv

        ret, data = self._context().modify_order(
            ModifyOrderOp.CANCEL,
            order_id=order_id,
            qty=0,
            price=0,
            trd_env=TrdEnv.SIMULATE,
        )
        rows = self._rows(ret, data, "cancel_order")
        return rows[0] if rows else {}

    @staticmethod
    def _rows(ret: int, data, operation: str) -> list[dict[str, Any]]:
        if ret != 0:
            raise RuntimeError(f"Futu simulated {operation} failed: {data}")
        return data.to_dict("records") if hasattr(data, "to_dict") else []
