"""Technical indicators used both to define a "dip" and as ML features."""

# Lets type hints work without issue in this Python version.
from __future__ import annotations

# numpy for math helpers (like "replace 0 with NaN" below); pandas for
# the DataFrame/Series types these indicators are computed on.
import numpy as np
import pandas as pd


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    # Work on a copy, not the original - callers shouldn't have their
    # input DataFrame silently mutated just because they called this.
    out = df.copy()
    close = out["Close"]  # the closing price series everything below is derived from

    # sma = "simple moving average" - the plain average of the last N
    # closing prices, recalculated fresh at every single row/bar.
    out["sma20"] = close.rolling(20).mean()  # average of the last 20 bars
    out["sma50"] = close.rolling(50).mean()  # average of the last 50 bars
    # How far below (negative) or above (positive) its own 20-period
    # average the current price is, as a fraction - this is literally
    # what "is this a dip" is measured against everywhere in this project.
    out["pct_below_sma20"] = (close - out["sma20"]) / out["sma20"]

    # % change in price over the last 1 / 5 / 10 bars - short-term
    # momentum readings, used as ML features (not by the rule-based
    # strategies, which only look at pct_below_sma20).
    out["ret1"] = close.pct_change(1)
    out["ret5"] = close.pct_change(5)
    out["ret10"] = close.pct_change(10)

    # Rolling standard deviation of 1-bar returns - a measure of how
    # choppy/volatile price has been recently, over two different window
    # lengths (10 bars vs. 20 bars).
    out["vol10"] = out["ret1"].rolling(10).std()
    out["vol20"] = out["ret1"].rolling(20).std()

    # RSI (Relative Strength Index) - a classic 0-100 momentum indicator;
    # see the _rsi() function below for exactly how it's computed.
    out["rsi14"] = _rsi(close, 14)

    # Highest closing price seen in the last 20 bars, and how far below
    # that recent peak the current price has fallen - a "drawdown from
    # recent high" reading, distinct from pct_below_sma20 (which compares
    # against a moving *average*, not a recent *peak*).
    roll_max20 = close.rolling(20).max()
    out["drawdown20"] = (close - roll_max20) / roll_max20

    return out


def _rsi(series: pd.Series, window: int) -> pd.Series:
    # Bar-over-bar price change - positive on an up move, negative on a
    # down move, NaN for the very first row (nothing to compare it to).
    delta = series.diff()
    # Keep only the up-moves (positive changes); clip(lower=0) turns any
    # negative value into 0, leaving gains untouched.
    gain = delta.clip(lower=0)
    # Keep only the down-moves, flipped to a positive number. clip(upper=0)
    # turns any positive value into 0 (so up-moves contribute nothing
    # here), then the leading "-" flips the remaining negative values
    # (down-moves) into positive loss magnitudes.
    loss = -delta.clip(upper=0)
    # Average gain and average loss over the trailing window - the two
    # ingredients RSI is built from.
    avg_gain = gain.rolling(window).mean()
    avg_loss = loss.rolling(window).mean()
    # "Relative strength" - ratio of average gain to average loss.
    # Replace 0 with NaN first so dividing by zero (a window with no
    # losses at all) produces a clean NaN instead of a math error/inf.
    rs = avg_gain / avg_loss.replace(0, np.nan)
    # The standard RSI formula, converting that ratio into a 0-100 scale.
    rsi = 100 - (100 / (1 + rs))
    # Wherever RSI came out as NaN (not enough history yet, or the
    # divide-by-zero case above), default to 50 - the neutral midpoint,
    # meaning "no opinion" rather than leaving a gap in the data.
    return rsi.fillna(50)


# The exact set of columns the ML model (src/model.py) is trained and
# predicted on - deliberately excludes raw price/SMA columns like
# "Close" or "sma20" themselves, using only the *relative*/normalized
# readings above so the model generalizes across tickers with wildly
# different price levels (e.g. a $0.07 coin vs. a $700 stock).
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
