"""
Tests for src/data.py's get_price_data_smart() routing logic: crypto
tickers should try Alpaca's historical bars first and only fall back to
Yahoo Finance (then synthetic) if Alpaca comes up short; non-crypto
tickers should never touch Alpaca at all. No real network calls happen
here - src.alpaca_data.get_crypto_bars_range and src.data._fetch_real
are monkeypatched.
"""

import pandas as pd

from src.data import get_price_data_smart


def _fake_bars(n=100):
    idx = pd.date_range("2025-01-01", periods=n, freq="5min", tz="UTC")
    return pd.DataFrame({"Close": range(n)}, index=idx)


def test_crypto_uses_alpaca_when_it_has_enough_bars(monkeypatch):
    monkeypatch.setattr("src.alpaca_data.get_crypto_bars_range", lambda *a, **k: _fake_bars(100))
    df, is_synthetic, source = get_price_data_smart("BTC-USD", "2025-01-01", "2025-01-05", interval="5m")
    assert source == "alpaca"
    assert not is_synthetic
    assert len(df) == 100


def test_crypto_falls_back_to_yahoo_when_alpaca_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("Alpaca has no bars for this range")
    monkeypatch.setattr("src.alpaca_data.get_crypto_bars_range", boom)
    # Force the Yahoo path (inside get_price_data()) to also come up
    # empty, so the outcome is deterministic (synthetic) rather than
    # depending on this sandbox's real network access.
    monkeypatch.setattr("src.data._fetch_real", lambda *a, **k: None)
    df, is_synthetic, source = get_price_data_smart("BTC-USD", "2025-01-01", "2025-01-05", interval="5m", seed=1)
    assert source == "synthetic"
    assert is_synthetic


def test_crypto_falls_back_when_alpaca_returns_too_few_bars(monkeypatch):
    # Alpaca "succeeding" with only a handful of bars shouldn't be
    # trusted any more than Yahoo returning a near-empty result would be.
    monkeypatch.setattr("src.alpaca_data.get_crypto_bars_range", lambda *a, **k: _fake_bars(10))
    monkeypatch.setattr("src.data._fetch_real", lambda *a, **k: None)
    df, is_synthetic, source = get_price_data_smart("BTC-USD", "2025-01-01", "2025-01-05", interval="5m", seed=1)
    assert source == "synthetic"


def test_non_crypto_ticker_never_calls_alpaca(monkeypatch):
    def should_not_be_called(*a, **k):
        raise AssertionError("get_crypto_bars_range must not be called for a stock ticker")
    monkeypatch.setattr("src.alpaca_data.get_crypto_bars_range", should_not_be_called)
    monkeypatch.setattr("src.data._fetch_real", lambda *a, **k: None)
    df, is_synthetic, source = get_price_data_smart("SPY", "2025-01-01", "2025-01-05", interval="1d", seed=1)
    assert source == "synthetic"
    assert is_synthetic
