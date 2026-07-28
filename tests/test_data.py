"""
Tests for src/data.py's get_price_data_smart() routing logic:
  - Crypto tickers always try Alpaca's historical bars first, falling
    back to Yahoo Finance (then synthetic) if Alpaca comes up short.
  - Stock tickers try Alpaca too, but ONLY for an intraday interval
    (interval != "1d") - a daily-bar stock request always goes straight
    to Yahoo, since Yahoo's daily history is already decades deep and
    there's no 60-day intraday cap to route around for it.
No real network calls happen here - src.alpaca_data.get_crypto_bars_range/
get_stock_bars_range and src.data._fetch_real are monkeypatched.
"""

import pandas as pd

from src.data import get_price_data_smart, periods_per_year


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


def test_daily_stock_never_calls_alpaca(monkeypatch):
    # Daily bars have no 60-day intraday cap to route around, so a
    # daily-bar stock request should skip Alpaca entirely and go
    # straight to Yahoo (then synthetic, if Yahoo itself is unreachable).
    def should_not_be_called(*a, **k):
        raise AssertionError("get_stock_bars_range must not be called for a daily-bar stock request")
    monkeypatch.setattr("src.alpaca_data.get_stock_bars_range", should_not_be_called)
    monkeypatch.setattr("src.data._fetch_real", lambda *a, **k: None)
    df, is_synthetic, source = get_price_data_smart("SPY", "2025-01-01", "2025-01-05", interval="1d", seed=1)
    assert source == "synthetic"
    assert is_synthetic


def test_intraday_stock_uses_alpaca_when_it_has_enough_bars(monkeypatch):
    monkeypatch.setattr("src.alpaca_data.get_stock_bars_range", lambda *a, **k: _fake_bars(100))
    df, is_synthetic, source = get_price_data_smart("SPY", "2025-01-01", "2025-01-05", interval="5m")
    assert source == "alpaca"
    assert not is_synthetic
    assert len(df) == 100


def test_intraday_stock_falls_back_to_yahoo_when_alpaca_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("Alpaca has no bars for this range")
    monkeypatch.setattr("src.alpaca_data.get_stock_bars_range", boom)
    monkeypatch.setattr("src.data._fetch_real", lambda *a, **k: None)
    df, is_synthetic, source = get_price_data_smart("SPY", "2025-01-01", "2025-01-05", interval="5m", seed=1)
    assert source == "synthetic"
    assert is_synthetic


def test_intraday_stock_falls_back_when_alpaca_returns_too_few_bars(monkeypatch):
    monkeypatch.setattr("src.alpaca_data.get_stock_bars_range", lambda *a, **k: _fake_bars(10))
    monkeypatch.setattr("src.data._fetch_real", lambda *a, **k: None)
    df, is_synthetic, source = get_price_data_smart("SPY", "2025-01-01", "2025-01-05", interval="5m", seed=1)
    assert source == "synthetic"


def test_periods_per_year_intraday_differs_by_asset_class():
    # Stocks only trade regular market hours, ~252 days/year - crypto
    # trades around the clock. Reusing crypto's 24/7 count for an
    # intraday stock bar (the pre-fix behavior) overstated how many bars
    # occur in a year, inflating annualized return/vol/Sharpe.
    stock_5m = periods_per_year("5m", is_crypto=False)
    crypto_5m = periods_per_year("5m", is_crypto=True)
    assert stock_5m < crypto_5m
    assert stock_5m == 252 * 78


def test_periods_per_year_daily_is_252_regardless_of_asset_class():
    assert periods_per_year("1d", is_crypto=False) == 252
    assert periods_per_year("1d", is_crypto=True) == 252


def test_periods_per_year_unknown_interval_falls_back_to_252():
    assert periods_per_year("1w", is_crypto=False) == 252
    assert periods_per_year("1w", is_crypto=True) == 252


def test_periods_per_year_4h_crypto_uses_24_7_calendar():
    # "4h" is a real, supported live-trading interval for crypto (see
    # live_trade.py/src/alpaca_data.py) but was missing from
    # PERIODS_PER_YEAR_24_7 - a 4h crypto backtest silently fell through
    # to the 252 stock-calendar fallback instead of a 24/7 count, wrongly
    # scaling its annualized return/vol/Sharpe.
    assert periods_per_year("4h", is_crypto=True) == 365 * 24 // 4
    assert periods_per_year("4h", is_crypto=True) != 252
