"""
Crypto price data via Alpaca's own market data API, for live trading.

Yahoo Finance's intraday crypto bars can go stale for hours without
throwing an error - it just silently serves an old bar as if it were
current, which is worse than an outright failure since nothing looks
wrong. This pulls from Alpaca instead: the same venue trades actually
execute against, continuously updating, and explicitly checked for
staleness before being trusted.

Only used for crypto in live_trade.py. Backtesting (main.py) still uses
Yahoo Finance via src/data.py - staleness doesn't matter for historical
data, and Yahoo gives a much longer history window than Alpaca's crypto
feed does.
"""

from __future__ import annotations

import datetime as dt
import os

import pandas as pd
from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
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

# How old the latest bar is allowed to be before we treat the feed as
# stale rather than trade on it. Generous multiple of the bar size.
_STALENESS_MINUTES = {
    "1m": 5, "5m": 15, "15m": 30, "30m": 45, "1h": 90, "4h": 300, "1d": 60 * 24 * 2,
}


def get_crypto_bars(symbol: str, interval: str, lookback_days: int) -> pd.DataFrame:
    """
    symbol: Alpaca-format crypto symbol, e.g. "BTC/USD".
    Returns a DataFrame with a DatetimeIndex and a "Close" column
    (freshest bar last) - same shape src/data.py produces, so it drops
    straight into add_features(). Raises if Alpaca has no bars, or if
    the latest bar is older than a sane threshold for that interval.
    """
    amount, unit = _INTERVAL_MAP.get(interval, (5, TimeFrameUnit.Minute))

    client = CryptoHistoricalDataClient(
        api_key=os.environ.get("ALPACA_API_KEY"),
        secret_key=os.environ.get("ALPACA_SECRET_KEY"),
    )
    end = dt.datetime.now(dt.timezone.utc)
    start = end - dt.timedelta(days=lookback_days)

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

    df = df.rename(columns={"close": "Close"})[["Close"]]

    last_ts = df.index[-1]
    if getattr(last_ts, "tzinfo", None) is None:
        last_ts = last_ts.tz_localize("UTC")
    age_minutes = (end - last_ts).total_seconds() / 60
    threshold = _STALENESS_MINUTES.get(interval, 30)
    if age_minutes > threshold:
        raise RuntimeError(
            f"Latest {symbol} bar is {age_minutes:.0f} min old (threshold {threshold} min) - "
            f"data looks stale, refusing to trade on it"
        )

    return df
