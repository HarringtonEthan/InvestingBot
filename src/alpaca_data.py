"""
Price data via Alpaca's own market data API - crypto and stocks.

Used two ways:
  - Live trading (`get_crypto_bars`): Yahoo Finance's intraday crypto bars
    can go stale for hours without throwing an error - it just silently
    serves an old bar as if it were current, which is worse than an
    outright failure since nothing looks wrong. This pulls from Alpaca
    instead: the same venue trades actually execute against, continuously
    updating, and explicitly checked for staleness before being trusted.
  - Historical/backtesting (`get_crypto_bars_range`, `get_stock_bars_range`):
    Yahoo Finance's intraday history is capped at roughly 60 days
    regardless of ticker, which makes real walk-forward validation of an
    intraday strategy impossible past that window. Alpaca isn't subject
    to that same free-tier retention cap, so `src/data.py`'s
    `get_price_data_smart()` tries Alpaca first for an intraday request
    before falling back to Yahoo.

Stock bars use Alpaca's free IEX feed (`DataFeed.IEX`) rather than the
full-market SIP feed, since SIP requires a separate market data
subscription this project doesn't have. IEX is a single exchange's view,
not the consolidated tape, so its bars can differ slightly from Yahoo's -
fine for backtesting (the strategy only needs a realistic, consistent
series), not something to treat as an execution-quality guarantee.
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
# Alpaca's market-data clients (separate from the trading client in
# broker.py, which places orders rather than fetching prices) - one for
# crypto bars, one for stock bars.
from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.data.historical.stock import StockHistoricalDataClient
# DataFeed.IEX selects the free single-exchange feed for stock bars (the
# full-market SIP feed needs a separate paid subscription this project
# doesn't have) - not used for crypto, which has no feed distinction.
from alpaca.data.enums import DataFeed
# The request payload builders for asking for a range of historical bars,
# plus a single symbol's most recent individual trade (get_stock_latest_price).
from alpaca.data.requests import CryptoBarsRequest, StockBarsRequest, StockLatestTradeRequest
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


def get_stock_bars_range(symbol: str, interval: str, start: str, end: str) -> pd.DataFrame:
    """
    Historical/backtesting path for stocks - same contract as
    get_crypto_bars_range() (symbol is the plain ticker, e.g. "AAPL";
    start/end are date strings), but against Alpaca's stock market data
    endpoint instead of crypto. Only worth calling for intraday intervals -
    Yahoo Finance's daily stock history is already decades deep, so
    src/data.py only reaches for this when Yahoo's ~60-day intraday cap is
    actually the problem. Raises if Alpaca has no bars at all for this
    symbol/range (e.g. before the ticker existed, or before Alpaca's IEX
    history begins).
    """
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
        # Same as the crypto path - a single-symbol request can still come
        # back indexed by (symbol, timestamp).
        df = df.xs(symbol, level=0)

    return df.rename(columns={"close": "Close"})[["Close"]]


def get_stock_latest_price(symbol: str) -> float:
    """
    The single most recent individual trade price for a stock, straight
    from Alpaca's live trade feed - not a historical bar's close.

    Added because live trading found that even Alpaca's own free IEX
    historical-bars feed (get_stock_bars_range above, what
    live_trade.py's decision logic reads) can sit several percent away
    from Alpaca's own real-time pricing at the exact same moment -
    confirmed live on 2026-07-28 (see CHANGELOG.md): a 5-minute bar's
    close only reflects whenever that bar's window happened to end, not
    literally "right now," and IEX alone (a single exchange, not the
    consolidated tape) doesn't always agree closely with the true
    market. This is meant to correct just the single most recent data
    point of a bars series live_trade.py already fetched for its rolling
    indicators (SMA/RSI tolerate a few minutes of lag fine - that's what
    "rolling" means) - see live_trade.py's decide() for where the two
    get combined. Raises if Alpaca has no trade on record for this
    symbol at all (e.g. a bad ticker) - callers should treat that the
    same as any other per-ticker data failure, not something to guess a
    price for.
    """
    client = StockHistoricalDataClient(
        api_key=os.environ.get("ALPACA_API_KEY"),
        secret_key=os.environ.get("ALPACA_SECRET_KEY"),
    )
    request = StockLatestTradeRequest(symbol_or_symbols=symbol, feed=DataFeed.IEX)
    trades = client.get_stock_latest_trade(request)
    return float(trades[symbol].price)
