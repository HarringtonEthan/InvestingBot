"""
Crypto price data via Alpaca's own market data API.

Used two ways:
  - Live trading (`get_crypto_bars`): Yahoo Finance's intraday crypto bars
    can go stale for hours without throwing an error - it just silently
    serves an old bar as if it were current, which is worse than an
    outright failure since nothing looks wrong. This pulls from Alpaca
    instead: the same venue trades actually execute against, continuously
    updating, and explicitly checked for staleness before being trusted.
  - Historical/backtesting (`get_crypto_bars_range`): Yahoo Finance's
    intraday history is capped at roughly 60 days regardless of ticker,
    which makes real walk-forward validation of a 5-minute strategy
    impossible past that window. Alpaca isn't subject to that same
    free-tier retention cap, so `src/data.py`'s `get_price_data_smart()`
    tries this first for crypto tickers before falling back to Yahoo.
"""

# Lets type hints work without issue in this Python version.
from __future__ import annotations

# datetime for computing "now" and the lookback window, and for measuring
# how old the latest bar is; os for reading API credentials from the
# environment.
import datetime as dt
import os

# pandas for the DataFrame type this module returns.
import pandas as pd
# Alpaca's market-data client for crypto bars specifically (separate from
# the trading client in broker.py, which places orders rather than
# fetching prices).
from alpaca.data.historical.crypto import CryptoHistoricalDataClient
# The request payload builder for asking for a range of historical bars.
from alpaca.data.requests import CryptoBarsRequest
# Bar size is expressed as an (amount, unit) pair, e.g. 5 Minute bars.
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

# Maps this project's interval strings (matching yfinance's conventions,
# for consistency with src/data.py) to the (amount, unit) pairs Alpaca's
# API actually wants.
_INTERVAL_MAP = {
    "1m": (1, TimeFrameUnit.Minute),
    "5m": (5, TimeFrameUnit.Minute),
    "15m": (15, TimeFrameUnit.Minute),
    "30m": (30, TimeFrameUnit.Minute),
    "1h": (1, TimeFrameUnit.Hour),
    "4h": (4, TimeFrameUnit.Hour),
    "1d": (1, TimeFrameUnit.Day),
}

# How old the latest bar is allowed to be before we treat the feed as
# stale rather than trade on it. Generous multiple of the bar size.
_STALENESS_MINUTES = {
    "1m": 5, "5m": 15, "15m": 30, "30m": 45, "1h": 90, "4h": 300, "1d": 60 * 24 * 2,
}


def _fetch_bars(symbol: str, interval: str, start: dt.datetime, end: dt.datetime) -> pd.DataFrame:
    """
    Shared Alpaca fetch used by both get_crypto_bars() and
    get_crypto_bars_range() below: requests bars for [start, end] and
    returns a DataFrame with a DatetimeIndex and a "Close" column
    (freshest bar last) - same shape src/data.py produces, so it drops
    straight into add_features(). Raises if Alpaca has no bars at all
    for this symbol/range; doesn't check staleness - that's only
    meaningful for the live-trading caller, not a deliberately historical
    range.
    """
    # Look up the (amount, unit) pair for the requested interval; default
    # to 5-minute bars if given an interval string not in the map.
    amount, unit = _INTERVAL_MAP.get(interval, (5, TimeFrameUnit.Minute))

    # Market data doesn't need the paper/live distinction broker.py cares
    # about - crypto bars are the same regardless of which account type
    # is trading on them, so this client just needs valid credentials.
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
    # .df converts the SDK's response object into a pandas DataFrame.
    df = bars.df
    if df is None or df.empty:
        # No bars at all came back - can't proceed without data.
        raise RuntimeError(f"Alpaca returned no crypto bars for {symbol}")

    if isinstance(df.index, pd.MultiIndex):
        # When bars are requested this way, Alpaca can index the result
        # by (symbol, timestamp) even for a single symbol - drop the
        # symbol level, keeping just the timestamp index for this symbol's
        # rows.
        df = df.xs(symbol, level=0)

    # Alpaca's column is lowercase "close"; rename to "Close" to match the
    # convention used everywhere else in this project (src/data.py's
    # output), then keep only that column.
    return df.rename(columns={"close": "Close"})[["Close"]]


def get_crypto_bars(symbol: str, interval: str, lookback_days: int) -> pd.DataFrame:
    """
    Live-trading path: symbol is an Alpaca-format crypto symbol, e.g.
    "BTC/USD". Fetches the last lookback_days of bars and raises if the
    latest one is older than a sane threshold for that interval - a
    live trading decision should never act on stale data.
    """
    end = dt.datetime.now(dt.timezone.utc)
    start = end - dt.timedelta(days=lookback_days)
    df = _fetch_bars(symbol, interval, start, end)

    # Timestamp of the most recent bar received.
    last_ts = df.index[-1]
    if getattr(last_ts, "tzinfo", None) is None:
        # Ensure the timestamp is timezone-aware (UTC) before comparing it
        # to `end` (also UTC) - subtracting a naive and an aware datetime
        # would raise an error.
        last_ts = last_ts.tz_localize("UTC")
    # How many minutes old the latest bar is, right now.
    age_minutes = (end - last_ts).total_seconds() / 60
    threshold = _STALENESS_MINUTES.get(interval, 30)
    if age_minutes > threshold:
        # The feed hasn't updated recently enough to trust for a live
        # trading decision - refuse rather than silently act on stale data.
        raise RuntimeError(
            f"Latest {symbol} bar is {age_minutes:.0f} min old (threshold {threshold} min) - "
            f"data looks stale, refusing to trade on it"
        )

    return df


def get_crypto_bars_range(symbol: str, interval: str, start: str, end: str) -> pd.DataFrame:
    """
    Historical/backtesting path: symbol is an Alpaca-format crypto symbol
    (e.g. "BTC/USD"); start/end are date strings (e.g. "2024-06-01").
    Unlike get_crypto_bars() above, this takes an explicit date range
    instead of "lookback_days from right now," and never raises for
    staleness - a deliberately historical range is expected to be old.
    Raises if Alpaca has no bars at all for this symbol/range (e.g. the
    range predates when Alpaca started carrying this pair).
    """
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")
    return _fetch_bars(symbol, interval, start_ts, end_ts)
