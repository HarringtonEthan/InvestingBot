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
    stop_loss: float | None = None,
    stop_cooldown_bars: int = 0,
) -> pd.Series:
    """
    Simple mean-reversion rule:
      - Buy (go 100% long) when price is more than `dip_threshold` below its
        20-day SMA (a "dip").
      - Sell (go to cash) once price recovers back above the SMA
        (`exit_threshold`, default = the SMA itself) - OR, if `stop_loss` is
        given, once price falls that far below the actual entry price,
        whichever happens first. `stop_loss=None` (the default) preserves
        the original mean-reversion-only behavior: without it, this rule
        can ride a sustained downtrend indefinitely waiting for a recovery
        that may not come for a long time, if ever.
      - After a stop-loss exit specifically (not a normal recovery exit),
        refuse to re-buy for `stop_cooldown_bars` bars even if the dip
        condition is still met. Without this, a sustained decline can
        trigger the same stop-loss over and over, turning one long
        unrealized drawdown into several smaller *realized* losses plus
        extra transaction costs - worse than what the stop-loss was meant
        to prevent.
    """
    pct_below = df["pct_below_sma20"].to_numpy()
    close = df["Close"].to_numpy()
    position = np.zeros(len(df))
    holding = False
    entry_price = None
    cooldown_remaining = 0

    for i in range(len(df)):
        val = pct_below[i]
        if np.isnan(val):
            position[i] = 0.0
            continue
        if not holding:
            if cooldown_remaining > 0:
                cooldown_remaining -= 1
            elif val <= dip_threshold:
                holding = True
                entry_price = close[i]
        else:
            recovered = val >= exit_threshold
            stopped_out = stop_loss is not None and (close[i] / entry_price - 1.0) <= -stop_loss
            if recovered or stopped_out:
                holding = False
                entry_price = None
                if stopped_out and not recovered:
                    cooldown_remaining = stop_cooldown_bars
        position[i] = 1.0 if holding else 0.0

    return pd.Series(position, index=df.index)


def day_trading_decision(
    holding: bool,
    entry_price: float | None,
    current_price: float,
    pct_below_sma20: float,
    dip_threshold: float,
    profit_target: float,
    stop_loss: float,
) -> str:
    """
    The single-step buy/sell/hold rule behind the day_trading strategy,
    factored out into its own pure function so a backtest and any live
    execution code both call this exact same logic instead of maintaining
    two copies that could silently drift apart. Returns "BUY", "SELL", or
    "HOLD".
    """
    if not holding:
        if not np.isnan(pct_below_sma20) and pct_below_sma20 <= dip_threshold:
            return "BUY"
        return "HOLD"
    else:
        gain = current_price / entry_price - 1.0
        if gain >= profit_target or gain <= -stop_loss:
            return "SELL"
        return "HOLD"


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
      - Sell once price is `profit_target` above where you bought.
      - Sell at a loss if price falls `stop_loss` below your entry first.
    Whichever threshold is hit first wins.
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
        action = day_trading_decision(holding, entry_price, price, pb, dip_threshold, profit_target, stop_loss)
        if action == "BUY":
            holding = True
            entry_price = price
        elif action == "SELL":
            holding = False
            entry_price = None
        position[i] = 1.0 if holding else 0.0

    return pd.Series(position, index=df.index)


def position_for_params(strategy: str, df: pd.DataFrame, params: dict, model=None, threshold: float | None = None) -> pd.Series:
    """
    Builds a position series for one of the three strategies below, given
    its own parameter shape:
      - "day_trading": {"dip_threshold", "profit_target", "stop_loss"}
      - "rule_based": {"dip_threshold", "exit_threshold"} (+ optional
        "stop_loss"/"stop_cooldown_bars")
      - "ml_filtered": {"dip_threshold", "exit_threshold"} + a trained
        `model`/calibrated `threshold` passed in separately
    Exists so optimize.py's grid search and walk_forward.py's validation
    both call through this one dispatch point instead of each keeping its
    own copy of "which strategy takes which parameters."
    """
    if strategy == "day_trading":
        return dip_buy_profit_target(
            df, dip_threshold=params["dip_threshold"],
            profit_target=params["profit_target"], stop_loss=params["stop_loss"],
        )
    if strategy == "rule_based":
        return rule_based_dip_buy(
            df, dip_threshold=params["dip_threshold"], exit_threshold=params["exit_threshold"],
            stop_cooldown_bars=params.get("stop_cooldown_bars", 0),
            stop_loss=params.get("stop_loss"),
        )
    if strategy == "ml_filtered":
        if model is None or threshold is None:
            raise ValueError("ml_filtered requires both model and threshold to be provided")
        return ml_filtered_dip_buy(
            df, model, threshold,
            dip_threshold=params["dip_threshold"], exit_threshold=params["exit_threshold"],
        )
    raise ValueError(f"unknown strategy: {strategy}")


def bollinger_breakout(
    df: pd.DataFrame,
    bb_window: int = 20,
    bb_std: float = 2.0,
    trend_window: int = 200,
) -> pd.Series:
    """
    Trend-following breakout - the opposite bet from the dip-buying
    strategies above:
      - Buy when price closes *above* its upper Bollinger Band (a
        20-period SMA plus `bb_std` standard deviations) AND above a
        long `trend_window`-period SMA - i.e. a strong upward breakout
        confirmed by the longer-term trend, not a dip.
      - Sell once price closes back below the middle band (the
        `bb_window`-period SMA itself), signaling the breakout has lost
        momentum.
    Mean-reversion strategies bet a drop will bounce back; this bets a
    breakout will keep going. Neither is universally better - it depends
    on whether the market is trending or range-bound. Backtest before
    trusting either on real capital.
    """
    close = df["Close"]
    middle = close.rolling(bb_window).mean()
    std = close.rolling(bb_window).std()
    upper = middle + bb_std * std
    trend = close.rolling(trend_window).mean()

    close_v = close.to_numpy()
    upper_v = upper.to_numpy()
    middle_v = middle.to_numpy()
    trend_v = trend.to_numpy()

    position = np.zeros(len(df))
    holding = False
    for i in range(len(df)):
        if np.isnan(upper_v[i]) or np.isnan(trend_v[i]):
            position[i] = 0.0
            continue
        if not holding and close_v[i] > upper_v[i] and close_v[i] > trend_v[i]:
            holding = True
        elif holding and close_v[i] < middle_v[i]:
            holding = False
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
