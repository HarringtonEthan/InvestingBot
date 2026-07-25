"""
Trading strategies. Each strategy is a function that takes a feature
dataframe and returns a pandas Series of target position sizes in [0, 1]
(fraction of capital to hold in the asset), indexed the same as the input.

Positions are decided using only information available as of that day's
close (no lookahead) and are assumed to be entered at the *next* day's
close in the backtest engine.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .features import FEATURE_COLUMNS


def buy_and_hold(df: pd.DataFrame) -> pd.Series:
    return pd.Series(1.0, index=df.index)


def rule_based_dip_buy(
    df: pd.DataFrame,
    dip_threshold: float = -0.03,
    exit_threshold: float = 0.0,
) -> pd.Series:
    """
    Simple mean-reversion rule:
      - Buy (go 100% long) when price is more than `dip_threshold` below its
        20-day SMA (a "dip").
      - Sell (go to cash) once price recovers back above the SMA
        (`exit_threshold`, default = the SMA itself).
      - Otherwise hold whatever position we're currently in.
    """
    pct_below = df["pct_below_sma20"]
    position = np.zeros(len(df))
    holding = False

    pct_below_vals = pct_below.to_numpy()
    for i in range(len(df)):
        val = pct_below_vals[i]
        if np.isnan(val):
            position[i] = 0.0
            continue
        if not holding and val <= dip_threshold:
            holding = True
        elif holding and val >= exit_threshold:
            holding = False
        position[i] = 1.0 if holding else 0.0

    return pd.Series(position, index=df.index)


def dip_buy_profit_target(
    df: pd.DataFrame,
    dip_threshold: float = -0.02,
    profit_target: float = 0.02,
    stop_loss: float = 0.04,
) -> pd.Series:
    """
    Day-trading variant: buy a dip (same signal as `rule_based_dip_buy`),
    but exit based on your actual entry price instead of the moving
    average:
      - Sell once price is `profit_target` above where you bought (a real
        profit, not just "back to normal").
      - Sell at a loss if price falls `stop_loss` below your entry first -
        without this, a strategy that only sells "once it recovers" can
        ride a sustained downtrend indefinitely waiting for a recovery
        that may not come for a long time, if ever.
    Whichever threshold is hit first wins. For backtesting, entry price is
    this bar's close; live trading uses the broker's actual average entry
    price instead (see live_trade.py), which is the real number that
    matters once money is involved.
    """
    pct_below = df["pct_below_sma20"].to_numpy()
    close = df["Close"].to_numpy()
    position = np.zeros(len(df))
    holding = False
    entry_price = None

    for i in range(len(df)):
        pb = pct_below[i]
        price = close[i]
        if np.isnan(pb):
            position[i] = 0.0
            continue
        if not holding:
            if pb <= dip_threshold:
                holding = True
                entry_price = price
        else:
            gain = price / entry_price - 1.0
            if gain >= profit_target or gain <= -stop_loss:
                holding = False
                entry_price = None
        position[i] = 1.0 if holding else 0.0

    return pd.Series(position, index=df.index)


def ml_filtered_dip_buy(
    df: pd.DataFrame,
    model,
    threshold: float,
    dip_threshold: float = -0.03,
    exit_threshold: float = 0.0,
) -> pd.Series:
    """
    Same dip/recovery rule as `rule_based_dip_buy`, but a dip is only acted
    on if the ML model's predicted bounce-probability on that day is at or
    above `threshold`. `threshold` should be calibrated from the model's
    own training-set score distribution (see model.py), never picked to
    make the test-set result look good.
    """
    pct_below = df["pct_below_sma20"].to_numpy()
    feats = df[FEATURE_COLUMNS]
    valid = ~feats.isna().any(axis=1)

    scores = np.full(len(df), np.nan)
    if valid.any():
        scores[valid.to_numpy()] = model.predict_proba(feats[valid])[:, 1]

    position = np.zeros(len(df))
    holding = False
    for i in range(len(df)):
        pb = pct_below[i]
        score = scores[i]
        if np.isnan(pb):
            position[i] = 0.0
            continue
        if not holding:
            is_dip = pb <= dip_threshold
            if is_dip and not np.isnan(score) and score >= threshold:
                holding = True
        elif holding and pb >= exit_threshold:
            holding = False
        position[i] = 1.0 if holding else 0.0

    return pd.Series(position, index=df.index)
