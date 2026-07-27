"""
Tests for src/alpaca_data.py - previously had zero coverage at all,
despite being the sole data source get_price_data_smart() trusts first
for every intraday request (crypto always, stocks when interval != "1d").
No real network calls happen here - CryptoHistoricalDataClient/
StockHistoricalDataClient are monkeypatched to return a canned response
shaped like the real SDK's, so _fetch_bars()/get_stock_bars_range()'s
own parsing logic (MultiIndex handling, column rename, empty-response
handling) is exercised exactly as it runs in production.
"""

import datetime as dt
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from src.alpaca_data import get_crypto_bars, get_crypto_bars_range, get_stock_bars_range


def _fake_client(df: pd.DataFrame | None, method_name: str):
    """
    Builds a fake Alpaca client class (crypto or stock) whose
    get_crypto_bars()/get_stock_bars() method returns an object with a
    `.df` attribute set to the given DataFrame - the same shape the real
    alpaca-py SDK returns. Used in place of CryptoHistoricalDataClient/
    StockHistoricalDataClient so no real API key/network call is needed.
    """
    client_instance = MagicMock()
    setattr(client_instance, method_name, MagicMock(return_value=SimpleNamespace(df=df)))
    # A callable class stand-in: calling it with any (api_key, secret_key)
    # arguments just returns the same pre-built mock instance.
    return MagicMock(return_value=client_instance)


def _bars_df(index, closes):
    return pd.DataFrame({"close": closes}, index=index)


def test_get_crypto_bars_range_renames_close_column(monkeypatch):
    idx = pd.date_range("2025-01-01", periods=5, freq="5min", tz="UTC")
    fake_client_cls = _fake_client(_bars_df(idx, [1, 2, 3, 4, 5]), "get_crypto_bars")
    monkeypatch.setattr("src.alpaca_data.CryptoHistoricalDataClient", fake_client_cls)

    df = get_crypto_bars_range("BTC/USD", "5m", "2025-01-01", "2025-01-02")
    assert list(df.columns) == ["Close"]
    assert len(df) == 5


def test_get_crypto_bars_range_handles_multiindex(monkeypatch):
    # Alpaca can index a single-symbol response by (symbol, timestamp)
    # instead of just timestamp - must be flattened down to just the
    # timestamp index for this symbol's rows, not left as-is or crashed on.
    idx = pd.date_range("2025-01-01", periods=3, freq="5min", tz="UTC")
    multi_idx = pd.MultiIndex.from_product([["BTC/USD"], idx], names=["symbol", "timestamp"])
    fake_client_cls = _fake_client(_bars_df(multi_idx, [1, 2, 3]), "get_crypto_bars")
    monkeypatch.setattr("src.alpaca_data.CryptoHistoricalDataClient", fake_client_cls)

    df = get_crypto_bars_range("BTC/USD", "5m", "2025-01-01", "2025-01-02")
    assert len(df) == 3
    assert not isinstance(df.index, pd.MultiIndex)


def test_get_crypto_bars_range_raises_on_empty_response(monkeypatch):
    fake_client_cls = _fake_client(pd.DataFrame(), "get_crypto_bars")
    monkeypatch.setattr("src.alpaca_data.CryptoHistoricalDataClient", fake_client_cls)

    with pytest.raises(RuntimeError):
        get_crypto_bars_range("BTC/USD", "5m", "2025-01-01", "2025-01-02")


def test_get_crypto_bars_raises_on_stale_data(monkeypatch):
    # Latest bar is far older than the 5m interval's staleness threshold
    # (15 minutes) - a live trading decision must refuse to act on it.
    stale_time = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2)
    idx = pd.DatetimeIndex([stale_time])
    fake_client_cls = _fake_client(_bars_df(idx, [100]), "get_crypto_bars")
    monkeypatch.setattr("src.alpaca_data.CryptoHistoricalDataClient", fake_client_cls)

    with pytest.raises(RuntimeError, match="stale"):
        get_crypto_bars("BTC/USD", "5m", lookback_days=1)


def test_get_crypto_bars_accepts_fresh_data(monkeypatch):
    fresh_time = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)
    idx = pd.DatetimeIndex([fresh_time])
    fake_client_cls = _fake_client(_bars_df(idx, [100]), "get_crypto_bars")
    monkeypatch.setattr("src.alpaca_data.CryptoHistoricalDataClient", fake_client_cls)

    df = get_crypto_bars("BTC/USD", "5m", lookback_days=1)
    assert df["Close"].iloc[-1] == 100


def test_get_stock_bars_range_renames_close_column(monkeypatch):
    idx = pd.date_range("2025-01-01", periods=5, freq="5min", tz="UTC")
    fake_client_cls = _fake_client(_bars_df(idx, [10, 11, 12, 13, 14]), "get_stock_bars")
    monkeypatch.setattr("src.alpaca_data.StockHistoricalDataClient", fake_client_cls)

    df = get_stock_bars_range("AAPL", "5m", "2025-01-01", "2025-01-02")
    assert list(df.columns) == ["Close"]
    assert len(df) == 5


def test_get_stock_bars_range_handles_multiindex(monkeypatch):
    idx = pd.date_range("2025-01-01", periods=3, freq="5min", tz="UTC")
    multi_idx = pd.MultiIndex.from_product([["AAPL"], idx], names=["symbol", "timestamp"])
    fake_client_cls = _fake_client(_bars_df(multi_idx, [10, 11, 12]), "get_stock_bars")
    monkeypatch.setattr("src.alpaca_data.StockHistoricalDataClient", fake_client_cls)

    df = get_stock_bars_range("AAPL", "5m", "2025-01-01", "2025-01-02")
    assert len(df) == 3
    assert not isinstance(df.index, pd.MultiIndex)


def test_get_stock_bars_range_raises_on_empty_response(monkeypatch):
    fake_client_cls = _fake_client(pd.DataFrame(), "get_stock_bars")
    monkeypatch.setattr("src.alpaca_data.StockHistoricalDataClient", fake_client_cls)

    with pytest.raises(RuntimeError):
        get_stock_bars_range("AAPL", "5m", "2025-01-01", "2025-01-02")


def test_get_stock_bars_range_requests_iex_feed(monkeypatch):
    # Free-tier accounts don't have the SIP feed - every stock bars
    # request must explicitly ask for IEX, never the default feed.
    idx = pd.date_range("2025-01-01", periods=2, freq="5min", tz="UTC")
    client_instance = MagicMock()
    client_instance.get_stock_bars.return_value = SimpleNamespace(df=_bars_df(idx, [1, 2]))
    monkeypatch.setattr("src.alpaca_data.StockHistoricalDataClient", MagicMock(return_value=client_instance))

    get_stock_bars_range("AAPL", "5m", "2025-01-01", "2025-01-02")

    request = client_instance.get_stock_bars.call_args.args[0]
    from alpaca.data.enums import DataFeed
    assert request.feed == DataFeed.IEX
