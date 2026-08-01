"""
OPTIONAL: price data via Alpaca's market data API (crypto and stocks).

This module is only used if you've set ALPACA_API_KEY / ALPACA_SECRET_KEY
in your environment (a free Alpaca paper-trading account is enough - see
README). Everything in this toolkit works without it: src/data.py's
get_price_data() pulls from free Yahoo Finance data with no account or
API key required. This module exists purely to lift Yahoo's ~60-day
intraday-history cap for anyone validating a strategy on 5-minute/1-hour
bars over a longer real window than that.

Historical/backtesting (`get_crypto_bars_range`, `get_stock_bars_range`):
Yahoo Finance's intraday history is capped at roughly 60 days regardless
of ticker, which makes real walk-forward validation of an intraday
strategy impossible past that window. Alpaca isn't subject to that same
free-tier retention cap, so `src/data.py`'s `get_price_data_smart()`
tries Alpaca first for an intraday request before falling back to Yahoo.

Stock bars use Alpaca's free IEX feed (`DataFeed.IEX`) rather than the
full-market SIP feed, since SIP requires a separate market data
subscription. IEX is a single exchange's view, not the consolidated
tape, so its bars can differ slightly from Yahoo's - fine for
backtesting (the strategy only needs a realistic, consistent series),
not something to treat as an execution-quality guarantee.
"""

from __future__ import annotations

import datetime as dt
import os

import pandas as pd
from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.enums import DataFeed
from alpaca.data.requests import CryptoBarsRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

_INTERVAL_MAP = {
    "1m": (1, TimeFrameUnit.Minute),
    "5m": (5, TimeFrameUnit.Minute),
    "15m": (15, TimeFrameUnit.Minute),
    "30m": (30, TimeFrameUnit.Minute),
    "1h": (1, TimeFrameUnit.Hour),
    "4h": (4, TimeFrameUnit.Hour),
    "1d": (1, TimeFrameUnit.Day),
}

STALENESS_MINUTES = {
    "1m": 5, "5m": 15, "15m": 30, "30m": 45, "1h": 90, "4h": 300, "1d": 60 * 24 * 2,
}


def _fetch_bars(symbol: str, interval: str, start: dt.datetime, end: dt.datetime) -> pd.DataFrame:
    amount, unit = _INTERVAL_MAP.get(interval, (5, TimeFrameUnit.Minute))

    client = CryptoHistoricalDataClient(
        api_key=os.environ.get("ALPACA_API_KEY"),
        secret_key=os.environ.get("ALPACA_SECRET_KEY"),
    )
    request = CryptoBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame(amount, unit),
        start=start,
        end=end,
    )
    bars = client.get_crypto_bars(request)
    df = bars.df
    if df is None or df.empty:
        raise RuntimeError(f"Alpaca returned no crypto bars for {symbol}")

    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(symbol, level=0)

    return df.rename(columns={"close": "Close"})[["Close"]]


def get_crypto_bars(symbol: str, interval: str, lookback_days: int) -> pd.DataFrame:
    """Fetches the last lookback_days of bars and raises if the latest one is stale."""
    end = dt.datetime.now(dt.timezone.utc)
    start = end - dt.timedelta(days=lookback_days)
    df = _fetch_bars(symbol, interval, start, end)

    last_ts = df.index[-1]
    if getattr(last_ts, "tzinfo", None) is None:
        last_ts = last_ts.tz_localize("UTC")
    age_minutes = (end - last_ts).total_seconds() / 60
    threshold = STALENESS_MINUTES.get(interval, 30)
    if age_minutes > threshold:
        raise RuntimeError(
            f"Latest {symbol} bar is {age_minutes:.0f} min old (threshold {threshold} min) - "
            f"data looks stale, refusing to trust it"
        )

    return df


def get_crypto_bars_range(symbol: str, interval: str, start: str, end: str) -> pd.DataFrame:
    """Historical/backtesting path: explicit date range, never raises for staleness."""
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")
    return _fetch_bars(symbol, interval, start_ts, end_ts)


def get_stock_bars_range(symbol: str, interval: str, start: str, end: str) -> pd.DataFrame:
    """Historical/backtesting path for stocks - same contract as get_crypto_bars_range()."""
    amount, unit = _INTERVAL_MAP.get(interval, (5, TimeFrameUnit.Minute))

    client = StockHistoricalDataClient(
        api_key=os.environ.get("ALPACA_API_KEY"),
        secret_key=os.environ.get("ALPACA_SECRET_KEY"),
    )
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame(amount, unit),
        start=pd.Timestamp(start, tz="UTC"),
        end=pd.Timestamp(end, tz="UTC"),
        feed=DataFeed.IEX,
    )
    bars = client.get_stock_bars(request)
    df = bars.df
    if df is None or df.empty:
        raise RuntimeError(f"Alpaca returned no stock bars for {symbol}")

    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(symbol, level=0)

    return df.rename(columns={"close": "Close"})[["Close"]]
