"""
Price data loading.

Tries to pull real OHLCV data from Yahoo Finance via yfinance, at either
daily or intraday resolution. If that fails (no network access, rate
limiting, bad ticker, etc.) it falls back to a synthetic price series so
the rest of the pipeline can still be developed and tested offline.
Synthetic data is always clearly labeled - never treat it as a real
backtest result.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Crypto trades 24/7; yfinance's intraday intervals go back a limited
# window (Yahoo restricts how far "1h" bars go, for example), which is
# fine for a day-trading strategy that only needs recent history.
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
    try:
        df = _fetch_real(ticker, start, end, interval)
        if df is not None and len(df) > 50:
            return df, False
    except Exception:
        pass

    return _generate_synthetic(ticker, start, end, interval=interval, seed=seed), True


def _fetch_real(ticker: str, start: str, end: str, interval: str) -> pd.DataFrame | None:
    import yfinance as yf

    df = yf.download(ticker, start=start, end=end, interval=interval, progress=False, auto_adjust=True)
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
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
    rng = np.random.default_rng(seed)

    if interval == "1d":
        dates = pd.bdate_range(start=start, end=end)
        periods_per_year = 252
    else:
        freq = {"1h": "1h", "30m": "30min", "15m": "15min", "5m": "5min"}.get(interval, "1h")
        dates = pd.date_range(start=start, end=end, freq=freq)
        periods_per_year = PERIODS_PER_YEAR_24_7.get(interval, PERIODS_PER_YEAR_24_7["1h"])

    n = len(dates)
    if n == 0:
        raise ValueError("empty date range")

    annual_drift = 0.09
    annual_vol_base = 0.19
    dt = 1 / periods_per_year

    period_drift = annual_drift * dt
    base_period_vol = annual_vol_base * np.sqrt(dt)

    # Mean-reverting log-volatility (Ornstein-Uhlenbeck-ish) so vol clusters
    # instead of behaving like i.i.d. noise, but stays bounded.
    vol_mean = np.log(base_period_vol)
    vol = np.empty(n)
    log_vol = vol_mean
    kappa = 0.05
    vol_of_vol = 0.15
    for i in range(n):
        log_vol += kappa * (vol_mean - log_vol) + vol_of_vol * rng.normal()
        log_vol = np.clip(log_vol, vol_mean - 1.2, vol_mean + 1.2)
        vol[i] = np.exp(log_vol)

    shocks = rng.normal(size=n)
    log_returns = period_drift - 0.5 * vol**2 + vol * shocks

    log_price = np.cumsum(log_returns)
    price = 100 * np.exp(log_price)

    df = pd.DataFrame({"Close": price}, index=dates)
    return df
