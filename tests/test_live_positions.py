"""
Tests for visualize_log.py's --live-positions aggregation: summing each
open position's unrealized P&L into a crypto total and a stock total,
split by Broker.get_all_positions()'s is_crypto flag.
"""

from visualize_log import aggregate_unrealized_pnl


def test_aggregate_splits_by_asset_class():
    positions = [
        {"symbol": "BTC/USD", "is_crypto": True, "unrealized_pl": 50.0},
        {"symbol": "ETH/USD", "is_crypto": True, "unrealized_pl": -20.0},
        {"symbol": "DIS", "is_crypto": False, "unrealized_pl": 13.47},
        {"symbol": "CAT", "is_crypto": False, "unrealized_pl": -40.95},
    ]
    crypto_total, stock_total = aggregate_unrealized_pnl(positions)
    assert crypto_total == 30.0
    assert round(stock_total, 2) == -27.48


def test_aggregate_empty_positions_returns_zero():
    assert aggregate_unrealized_pnl([]) == (0.0, 0.0)


def test_aggregate_one_asset_class_only():
    positions = [{"symbol": "XOM", "is_crypto": False, "unrealized_pl": 9.29}]
    crypto_total, stock_total = aggregate_unrealized_pnl(positions)
    assert crypto_total == 0.0
    assert round(stock_total, 2) == 9.29


def test_fake_broker_get_all_positions_matches_real_broker_shape():
    from tests.fake_broker import FakeBroker

    broker = FakeBroker()
    broker.buy_notional("BTC/USD", 1000.0, is_crypto=True)
    broker.buy_notional("DIS", 2000.0, is_crypto=False)
    broker.set_unrealized_pl("BTC/USD", True, 25.0)
    broker.set_unrealized_pl("DIS", False, -13.0)

    positions = broker.get_all_positions()
    crypto_total, stock_total = aggregate_unrealized_pnl(positions)
    assert crypto_total == 25.0
    assert stock_total == -13.0
