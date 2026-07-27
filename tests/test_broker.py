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
