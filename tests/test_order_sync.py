from app.services.order_sync import sync_sim_orders


class SimProviderWithoutDeals:
    def get_open_orders(self):
        return []

    def get_deals(self):
        raise RuntimeError("Futu simulated deal_list_query failed: 模拟交易不支持成交数据")


class BrokenDealsProvider(SimProviderWithoutDeals):
    def get_deals(self):
        raise RuntimeError("OpenD connection failed")


def test_sim_loop_continues_when_futu_simulation_does_not_support_deals(session):
    result = sync_sim_orders(session, SimProviderWithoutDeals())

    assert result == {"updated": 0, "filled": 0, "deals_supported": False}


def test_unrelated_deal_sync_errors_are_not_hidden(session):
    try:
        sync_sim_orders(session, BrokenDealsProvider())
    except RuntimeError as exc:
        assert "OpenD connection failed" in str(exc)
    else:
        raise AssertionError("unexpected deal sync failures must still stop the loop")
