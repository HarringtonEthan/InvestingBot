"""
Price data loading.

Tries to pull real daily OHLCV data from Yahoo Finance via yfinance. If that
fails (no network access, rate limiting, bad ticker, etc.) it falls back to
a synthetic price series so the rest of the pipeline can still be developed
and tested offline. Synthetic data is always clearly labeled - never treat
it as a real backtest result.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def get_price_data(ticker: str, start: str, end: str, seed: int | None = None) -> tuple[pd.DataFrame, bool]:
    """
    Return (dataframe, is_synthetic).

    dataframe has a DatetimeIndex and a "Close" column at minimum.
    """
    try:
        df = _fetch_real(ticker, start, end)
        if df is not None and len(df) > 50:
            return df, False
    except Exception:
        pass

    return _generate_synthetic(ticker, start, end, seed=seed), True


def _fetch_real(ticker: str, start: str, end: str) -> pd.DataFrame | None:
    import yfinance as yf

    df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df[["Close"]].dropna()


def _generate_synthetic(ticker: str, start: str, end: str, seed: int | None = None) -> pd.DataFrame:
    """
    Generate a daily-close series that looks like a real equity: geometric
    Brownian motion with a mild mean-reverting volatility regime (so vol
    clusters like real markets do), calibrated to roughly:
      - ~8-10% annualized drift (long-run equity market average)
      - ~19% annualized volatility (SPY's long-run realized vol)
      - occasional drawdowns of 10-30%, not runaway crashes
    """
    rng = np.random.default_rng(seed)

    dates = pd.bdate_range(start=start, end=end)
    n = len(dates)
    if n == 0:
        raise ValueError("empty date range")

    annual_drift = 0.09
    annual_vol_base = 0.19
    dt = 1 / 252

    daily_drift = annual_drift * dt
    base_daily_vol = annual_vol_base * np.sqrt(dt)

    # Mean-reverting log-volatility (Ornstein-Uhlenbeck-ish) so vol clusters
    # instead of behaving like i.i.d. noise, but stays bounded.
    vol_mean = np.log(base_daily_vol)
    vol = np.empty(n)
    log_vol = vol_mean
    kappa = 0.05
    vol_of_vol = 0.15
    for i in range(n):
        log_vol += kappa * (vol_mean - log_vol) + vol_of_vol * rng.normal()
        log_vol = np.clip(log_vol, vol_mean - 1.2, vol_mean + 1.2)
        vol[i] = np.exp(log_vol)

    shocks = rng.normal(size=n)
    log_returns = daily_drift - 0.5 * vol**2 + vol * shocks

    log_price = np.cumsum(log_returns)
    price = 100 * np.exp(log_price)

    df = pd.DataFrame({"Close": price}, index=dates)
    return df
