from __future__ import annotations

from itertools import count


class MockTradeProvider:
    def __init__(self) -> None:
        self._ids = count(1)
        self.orders: list[dict] = []

    def close(self) -> None:
        pass

    def get_accounts(self):
        return [{"acc_id": "mock-sim", "trd_env": "SIMULATE"}]

    def get_account_info(self):
        return {"cash": 100_000, "power": 100_000}

    def get_positions(self):
        return []

    def get_open_orders(self):
        return list(self.orders)

    def get_deals(self):
        return []

    def place_simulated_order(self, symbol, side, qty, limit_price):
        row = {
            "order_id": f"mock-{next(self._ids)}",
            "code": f"US.{symbol}",
            "trd_side": side,
            "qty": qty,
            "price": limit_price,
            "order_status": "SUBMITTED",
            "trd_env": "SIMULATE",
        }
        self.orders.append(row)
        return row

    def cancel_order(self, order_id):
        return {"order_id": order_id, "order_status": "CANCELLED"}
