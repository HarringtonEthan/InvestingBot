"""
Tests for the stock market-hours guard: live_trade.py should refuse to
submit a stock BUY/SELL while the market is confirmed closed, closing
off the general case of the real incident where a stock order was
submitted (and later silently filled) outside market hours - see
CHANGELOG.md and src/broker.py's is_market_open() docstring. Crypto
trades 24/7 and must never be affected by this at all.
"""

from live_trade import stock_market_closed
from tests.fake_broker import FakeBroker


def test_stock_blocked_when_market_confirmed_closed():
    assert stock_market_closed(is_crypto=False, market_open=False) is True


def test_stock_allowed_when_market_confirmed_open():
    assert stock_market_closed(is_crypto=False, market_open=True) is False


def test_crypto_never_blocked_regardless_of_market_open_value():
    # Crypto trades 24/7 - market_open is never even checked for it in
    # main(), but this function must stay safe even if ever called with
    # market_open=False for a crypto decision by mistake.
    assert stock_market_closed(is_crypto=True, market_open=False) is False
    assert stock_market_closed(is_crypto=True, market_open=True) is False


def test_stock_not_blocked_when_never_checked():
    # market_open=None means an all-crypto run never called
    # is_market_open() at all - must not be mistaken for "confirmed closed".
    assert stock_market_closed(is_crypto=False, market_open=None) is False


def test_fake_broker_market_open_defaults_to_true():
    # Every existing test that never calls set_market_open() should keep
    # exercising the normal, market-open path without knowing this
    # attribute exists.
    broker = FakeBroker()
    assert broker.is_market_open() is True


def test_fake_broker_set_market_open():
    broker = FakeBroker()
    broker.set_market_open(False)
    assert broker.is_market_open() is False
