"""
Price data loading.

Tries to pull real OHLCV data from Yahoo Finance via yfinance, at either
daily or intraday resolution. If that fails (no network access, rate
limiting, bad ticker, etc.) it falls back to a synthetic price series so
the rest of the pipeline can still be developed and tested offline.
Synthetic data is always clearly labeled - never treat it as a real
backtest result.
"""

# Lets type hints refer to things defined later in the file / to "| None"
# style unions without Python complaining.
from __future__ import annotations

# numpy: fast math on arrays of numbers (used here for the random-walk
# price simulation). pandas: the DataFrame/table type used everywhere
# else in this project to hold price data with a date index.
import numpy as np
import pandas as pd

# Crypto trades 24/7; yfinance's intraday intervals go back a limited
# window (Yahoo restricts how far "1h" bars go, for example), which is
# fine for a day-trading strategy that only needs recent history.
# How many bars of each size occur in one year if trading never stops
# (24 hours a day, 365 days a year) - used to scale the synthetic-data
# generator's drift/volatility to whatever bar size was requested.
PERIODS_PER_YEAR_24_7 = {
    "1d": 365,
    "1h": 365 * 24,
    "30m": 365 * 24 * 2,
    "15m": 365 * 24 * 4,
    "5m": 365 * 24 * 12,
}


def get_price_data(
    ticker: str, start: str, end: str, interval: str = "1d", seed: int | None = None
) -> tuple[pd.DataFrame, bool]:
    """
    Return (dataframe, is_synthetic).

    dataframe has a DatetimeIndex and a "Close" column at minimum.
    `interval` follows yfinance conventions: "1d", "1h", "30m", "15m",
    "5m", etc. Intraday intervals are needed for a day-trading strategy;
    daily is what the longer-horizon dip-buy strategy uses.
    """
    # Try the real data source first; if anything goes wrong (network
    # error, bad ticker, empty result), silently fall through to the
    # synthetic generator below rather than crashing the whole program.
    try:
        df = _fetch_real(ticker, start, end, interval)
        # Require more than 50 rows so a near-empty/garbage response
        # doesn't get treated as "real data" - not enough to be useful
        # anyway, so it's better to fall back to synthetic in that case.
        if df is not None and len(df) > 50:
            return df, False  # False = "this is NOT synthetic data"
    except Exception:
        # Deliberately swallow any error type here - whatever went wrong
        # with the real fetch, the fallback below is the recovery path,
        # not re-raising the exception.
        pass

    # Real data unavailable or too sparse - generate a fake-but-realistic
    # series instead, and flag it as such (the True at the end).
    return _generate_synthetic(ticker, start, end, interval=interval, seed=seed), True


def _fetch_real(ticker: str, start: str, end: str, interval: str) -> pd.DataFrame | None:
    # Imported inside the function (not at the top of the file) so this
    # module can still be imported even in an environment where yfinance
    # itself might fail to import cleanly - only pays that cost if this
    # function actually gets called.
    import yfinance as yf

    # auto_adjust=True: prices are adjusted for splits/dividends, which
    # is what you want for backtesting (avoids fake "price drops" on a
    # split day that never really happened to your money).
    df = yf.download(ticker, start=start, end=end, interval=interval, progress=False, auto_adjust=True)
    # yfinance can return None or an empty table if the ticker/range was
    # bad - treat both as "no data" rather than crashing on the next line.
    if df is None or df.empty:
        return None
    # For some tickers/requests, yfinance returns columns as a MultiIndex
    # (e.g. ("Close", "AAPL")) instead of a plain "Close" - flatten it
    # down to just the first level so the rest of the code can rely on a
    # simple column name.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    # Keep only the Close column (nothing else in this project uses
    # Open/High/Low/Volume) and drop any rows where it's missing.
    return df[["Close"]].dropna()


def _generate_synthetic(
    ticker: str, start: str, end: str, interval: str = "1d", seed: int | None = None
) -> pd.DataFrame:
    """
    Generate a close-price series that looks like a real market: geometric
    Brownian motion with a mild mean-reverting volatility regime (so vol
    clusters like real markets do), calibrated to roughly:
      - ~8-10% annualized drift (long-run equity market average)
      - ~19% annualized volatility (SPY's long-run realized vol; crypto
        would realistically be higher, but this keeps the generator
        simple and it's only ever a stand-in for real data anyway)
      - occasional drawdowns of 10-30%, not runaway crashes

    `interval="1d"` produces business-day bars (matches stock market
    hours); any intraday interval produces continuous 24/7 bars (matches
    how crypto actually trades), scaled to that bar frequency.
    """
    # A seeded random number generator - same seed always produces the
    # exact same "random" sequence, which is what makes synthetic-data
    # demo runs reproducible instead of different every time.
    rng = np.random.default_rng(seed)

    if interval == "1d":
        # Business days only (Mon-Fri, no weekends) - matches how stock
        # markets actually trade.
        dates = pd.bdate_range(start=start, end=end)
        periods_per_year = 252  # standard number of US trading days/year
    else:
        # Map this project's interval strings to pandas' own frequency
        # codes; default to hourly if somehow given an unrecognized one.
        freq = {"1h": "1h", "30m": "30min", "15m": "15min", "5m": "5min"}.get(interval, "1h")
        # Continuous calendar time (includes weekends) - matches how
        # crypto actually trades, 24/7.
        dates = pd.date_range(start=start, end=end, freq=freq)
        periods_per_year = PERIODS_PER_YEAR_24_7.get(interval, PERIODS_PER_YEAR_24_7["1h"])

    n = len(dates)  # how many price bars we need to generate
    if n == 0:
        # Nothing to generate - almost certainly means start/end were
        # given in the wrong order or too close together.
        raise ValueError("empty date range")

    annual_drift = 0.09       # ~9%/year average upward drift, like long-run stock returns
    annual_vol_base = 0.19    # ~19%/year volatility, like long-run SPY volatility
    dt = 1 / periods_per_year  # length of one bar, expressed as a fraction of a year

    # Scale the annual drift/volatility down to "per bar" - e.g. a 5-minute
    # bar's expected drift is the annual drift divided into thousands of
    # tiny slices, not the full 9% applied every 5 minutes.
    period_drift = annual_drift * dt
    base_period_vol = annual_vol_base * np.sqrt(dt)  # volatility scales with sqrt(time), not time itself

    # Mean-reverting log-volatility (Ornstein-Uhlenbeck-ish) so vol clusters
    # instead of behaving like i.i.d. noise, but stays bounded.
    vol_mean = np.log(base_period_vol)  # the "resting" volatility level, in log space
    vol = np.empty(n)                   # will hold the actual volatility used at each bar
    log_vol = vol_mean                  # starting point: right at the resting level
    kappa = 0.05        # how strongly volatility gets pulled back toward its resting level each step
    vol_of_vol = 0.15    # how much randomness gets added to volatility itself each step
    for i in range(n):
        # Nudge log-volatility toward its mean, plus a random shock -
        # this is what creates "volatility clustering" (calm stretches
        # and choppy stretches) instead of every bar being equally wild.
        log_vol += kappa * (vol_mean - log_vol) + vol_of_vol * rng.normal()
        # Keep it within a sane range so volatility can't spiral off to
        # an absurd extreme over a long simulated period.
        log_vol = np.clip(log_vol, vol_mean - 1.2, vol_mean + 1.2)
        # Convert back out of log space into an actual volatility number
        # and store it for this bar.
        vol[i] = np.exp(log_vol)

    shocks = rng.normal(size=n)  # one random "surprise" per bar, standard normal (mean 0, spread 1)
    # The standard geometric Brownian motion formula for one period's
    # log-return: drift, minus a variance-correction term, plus that
    # bar's volatility times its random shock.
    log_returns = period_drift - 0.5 * vol**2 + vol * shocks

    # Summing log-returns and exponentiating is how you turn a series of
    # period-by-period % changes into an actual running price level.
    log_price = np.cumsum(log_returns)
    price = 100 * np.exp(log_price)  # start the series at an arbitrary $100

    # Package it in the exact same shape real data comes back in - a
    # DataFrame with a "Close" column and a datetime index - so nothing
    # downstream needs to know or care whether this is real or fake data.
    df = pd.DataFrame({"Close": price}, index=dates)
    return df
