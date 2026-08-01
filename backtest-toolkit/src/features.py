"""Technical indicators used both to define a "dip" and as ML features."""

from __future__ import annotations

import numpy as np
import pandas as pd


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    close = out["Close"]

    out["sma20"] = close.rolling(20).mean()
    out["sma50"] = close.rolling(50).mean()
    out["pct_below_sma20"] = (close - out["sma20"]) / out["sma20"]

    out["ret1"] = close.pct_change(1)
    out["ret5"] = close.pct_change(5)
    out["ret10"] = close.pct_change(10)

    out["vol10"] = out["ret1"].rolling(10).std()
    out["vol20"] = out["ret1"].rolling(20).std()

    out["rsi14"] = _rsi(close, 14)

    roll_max20 = close.rolling(20).max()
    out["drawdown20"] = (close - roll_max20) / roll_max20

    return out


def _rsi(series: pd.Series, window: int) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window).mean()
    avg_loss = loss.rolling(window).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    return rsi.fillna(50)


FEATURE_COLUMNS = [
    "pct_below_sma20",
    "ret1",
    "ret5",
    "ret10",
    "vol10",
    "vol20",
    "rsi14",
    "drawdown20",
]
