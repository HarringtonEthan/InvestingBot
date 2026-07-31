"""
Tests for src/broker.py's error-handling fix: previously, ANY APIError
during a position lookup (auth failure, rate limit, server error, not
just a genuine "position not found") was silently treated as "holding
zero" - the same failure shape as the crypto position-detection bug,
just from a different root cause.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.broker import Broker

from .fake_broker import make_not_found_error, make_server_error


def test_404_is_recognized_as_position_not_found():
    assert Broker._is_position_not_found(make_not_found_error()) is True


def test_500_is_not_recognized_as_position_not_found():
    assert Broker._is_position_not_found(make_server_error()) is False


def test_position_symbol_strips_slash_for_crypto():
    assert Broker._position_symbol("DOGE/USD") == "DOGEUSD"


def test_position_symbol_leaves_stock_tickers_unchanged():
    assert Broker._position_symbol("AAPL") == "AAPL"


def _broker_with_mock_client() -> Broker:
    # Builds a real Broker instance without running __init__ (which
    # would require real Alpaca credentials and construct a real SDK
    # client) - just gives it a mock client instead, so the actual
    # get_position_qty/get_position_avg_entry_price logic can be
    # exercised exactly as it runs in production.
    broker = Broker.__new__(Broker)
    broker.client = MagicMock()
    return broker


def test_get_position_qty_returns_zero_on_404():
    broker = _broker_with_mock_client()
    broker.client.get_open_position.side_effect = make_not_found_error()
    assert broker.get_position_qty("DOGE/USD") == 0.0


def test_get_position_qty_raises_on_real_error():
    broker = _broker_with_mock_client()
    broker.client.get_open_position.side_effect = make_server_error()
    with pytest.raises(Exception):
        broker.get_position_qty("DOGE/USD")


def test_get_position_qty_returns_real_qty_when_held():
    broker = _broker_with_mock_client()
    broker.client.get_open_position.return_value = SimpleNamespace(qty="12.5")
    assert broker.get_position_qty("DOGE/USD") == 12.5


def test_get_position_avg_entry_price_returns_none_on_404():
    broker = _broker_with_mock_client()
    broker.client.get_open_position.side_effect = make_not_found_error()
    assert broker.get_position_avg_entry_price("DOGE/USD") is None


def test_get_position_avg_entry_price_raises_on_real_error():
    broker = _broker_with_mock_client()
    broker.client.get_open_position.side_effect = make_server_error()
    with pytest.raises(Exception):
        broker.get_position_avg_entry_price("DOGE/USD")


def test_get_buying_power_returns_account_field():
    broker = _broker_with_mock_client()
    broker.client.get_account.return_value = SimpleNamespace(buying_power="12345.67")
    assert broker.get_buying_power() == 12345.67


def test_list_recent_filled_orders_excludes_non_filled_and_shapes_output():
    import datetime as dt

    from alpaca.trading.enums import OrderSide, OrderStatus

    broker = _broker_with_mock_client()
    filled = SimpleNamespace(
        symbol="AAPL", side=OrderSide.BUY, status=OrderStatus.FILLED,
        filled_qty="6.61153719", filled_avg_price="302.65",
        filled_at="2026-07-31T09:33:15Z",
    )
    # A DAY order that expired unfilled at market close - must never be
    # mistaken for a real fill just because it's in the same "closed"
    # status batch Alpaca's own filter returns.
    canceled = SimpleNamespace(
        symbol="XOM", side=OrderSide.BUY, status=OrderStatus.CANCELED,
        filled_qty=None, filled_avg_price=None, filled_at=None,
    )
    broker.client.get_orders.return_value = [filled, canceled]
    result = broker.list_recent_filled_orders(since=dt.datetime(2026, 7, 31, tzinfo=dt.timezone.utc))
    assert len(result) == 1
    assert result[0]["symbol"] == "AAPL"
    assert result[0]["side"] == "buy"
    assert result[0]["filled_qty"] == 6.61153719
    assert result[0]["filled_avg_price"] == 302.65
    assert result[0]["filled_at"] == "2026-07-31T09:33:15Z"
