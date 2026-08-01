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

PERIODS_PER_YEAR_24_7 = {
    "1d": 365,
    "4h": 365 * 24 // 4,
    "1h": 365 * 24,
    "30m": 365 * 24 * 2,
    "15m": 365 * 24 * 4,
    "5m": 365 * 24 * 12,
}

PERIODS_PER_YEAR_STOCK_INTRADAY = {
    "1h": 252 * 7,    # 6.5hr session, rounded up to 7 hourly bars/day
    "30m": 252 * 13,  # 6.5hr * 2
    "15m": 252 * 26,  # 6.5hr * 4
    "5m": 252 * 78,   # 6.5hr * 60 / 5
}


def periods_per_year(interval: str, is_crypto: bool) -> float:
    """
    How many bars of size `interval` occur in a year - the scaling factor
    run_backtest() uses to annualize return/volatility/Sharpe. Daily bars
    ("1d") use 252 (standard US trading days) regardless of asset class.
    Anything intraday splits by asset class: crypto uses
    PERIODS_PER_YEAR_24_7 (it really does trade around the clock);
    stocks use PERIODS_PER_YEAR_STOCK_INTRADAY (they don't).
    """
    if interval == "1d":
        return 252
    table = PERIODS_PER_YEAR_24_7 if is_crypto else PERIODS_PER_YEAR_STOCK_INTRADAY
    return table.get(interval, 252)


def get_price_data(
    ticker: str, start: str, end: str, interval: str = "1d", seed: int | None = None
) -> tuple[pd.DataFrame, bool]:
    """
    Return (dataframe, is_synthetic).

    dataframe has a DatetimeIndex and a "Close" column at minimum.
    `interval` follows yfinance conventions: "1d", "1h", "30m", "15m",
    "5m", etc.
    """
    try:
        df = _fetch_real(ticker, start, end, interval)
        if df is not None and len(df) > 50:
            return df, False
    except Exception as e:
        print(f"[{ticker}] Real data fetch failed ({type(e).__name__}: {e}) - falling back to synthetic data.")

    return _generate_synthetic(ticker, start, end, interval=interval, seed=seed), True


def get_price_data_smart(
    ticker: str, start: str, end: str, interval: str = "1d", seed: int | None = None
) -> tuple[pd.DataFrame, bool, str]:
    """
    Same contract as get_price_data() (a Close-only DataFrame), but for
    crypto tickers tries Alpaca's historical crypto bars FIRST, not Yahoo
    Finance (only relevant if you've set up ALPACA_API_KEY/ALPACA_SECRET_KEY -
    entirely optional, see README). Yahoo's ~60-day intraday history window
    is a hard ceiling that makes real walk-forward validation of an
    intraday strategy impossible past that window; Alpaca isn't subject
    to that same free-tier retention cap.

    Returns (dataframe, is_synthetic, source), where source is one of
    "alpaca", "yahoo", or "synthetic". Falls back to get_price_data()
    (Yahoo, then synthetic) if Alpaca isn't configured, has too little
    data for this range, or isn't reachable.
    """
    from .symbols import resolve_symbol

    symbol = resolve_symbol(ticker)

    if symbol.is_crypto:
        try:
            from .alpaca_data import get_crypto_bars_range

            df = get_crypto_bars_range(symbol.alpaca, interval, start, end)
            if len(df) > 50:
                return df, False, "alpaca"
            print(f"[{ticker}] Alpaca returned only {len(df)} bars for this range (not enough) - "
                  f"falling back to Yahoo Finance.")
        except Exception as e:
            print(f"[{ticker}] Alpaca historical fetch failed ({type(e).__name__}: {e}) - falling back to Yahoo Finance.")
    elif interval != "1d":
        try:
            from .alpaca_data import get_stock_bars_range

            df = get_stock_bars_range(symbol.alpaca, interval, start, end)
            if len(df) > 50:
                return df, False, "alpaca"
            print(f"[{ticker}] Alpaca returned only {len(df)} bars for this range (not enough) - "
                  f"falling back to Yahoo Finance.")
        except Exception as e:
            print(f"[{ticker}] Alpaca historical fetch failed ({type(e).__name__}: {e}) - falling back to Yahoo Finance.")

    df, is_synthetic = get_price_data(symbol.yfinance, start, end, interval=interval, seed=seed)
    return df, is_synthetic, ("synthetic" if is_synthetic else "yahoo")


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
      - ~19% annualized volatility (SPY's long-run realized vol)
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
