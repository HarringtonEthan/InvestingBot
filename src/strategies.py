"""
Trading strategies. Each strategy is a function that takes a feature
dataframe and returns a pandas Series of target position sizes in [0, 1]
(fraction of capital to hold in the asset), indexed the same as the input.

Positions are decided using only information available as of that day's
close (no lookahead) and are assumed to be entered at the *next* day's
close in the backtest engine.
"""

# Lets type hints work without issue in this Python version.
from __future__ import annotations

# numpy for fast array math (building the position series bar by bar);
# pandas for the DataFrame/Series types strategies read and return.
import numpy as np
import pandas as pd

# The exact list of columns the ML model expects as input - imported so
# ml_filtered_dip_buy() below can pull exactly those columns, in the
# right set, out of a bigger feature DataFrame.
from .features import FEATURE_COLUMNS


def buy_and_hold(df: pd.DataFrame) -> pd.Series:
    # The simplest possible "strategy": 100% invested (1.0) at every
    # single bar, from the first row to the last - never buys or sells,
    # just holds the whole time. Used as the baseline everything else in
    # this project gets compared against.
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
    # How far below (or above) its own rolling average the price is at
    # each bar - this is the "is it a dip" signal the whole rule runs on.
    pct_below = df["pct_below_sma20"]
    # Will hold the final 0.0/1.0 decision for every bar; starts as all
    # zeros (out of the market) and gets filled in as the loop runs.
    position = np.zeros(len(df))
    # Whether we're currently "in" the trade, as the loop steps through
    # time bar by bar - this is the memory that makes the strategy
    # stateful (today's decision depends on yesterday's, not just today's
    # price alone).
    holding = False

    # Converting to a plain numpy array first, then looping over it, is
    # noticeably faster in Python than looping over a pandas Series
    # directly - matters here since this runs once per bar, for however
    # many bars are in the backtest.
    pct_below_vals = pct_below.to_numpy()
    for i in range(len(df)):
        val = pct_below_vals[i]
        if np.isnan(val):
            # Not enough history yet to compute the SMA (e.g. the very
            # first 19 bars, before a 20-period average is even possible)
            # - stay flat rather than guess.
            position[i] = 0.0
            continue
        if not holding and val <= dip_threshold:
            # Not currently holding, and price has dropped at least
            # dip_threshold below its average - buy.
            holding = True
        elif holding and val >= exit_threshold:
            # Currently holding, and price has recovered back up to (or
            # above) the exit line - sell.
            holding = False
        # Whatever "holding" ended up as after the checks above, record
        # it as this bar's position: fully in (1.0) or fully out (0.0).
        position[i] = 1.0 if holding else 0.0

    # Wrap the plain numpy array back into a pandas Series, reusing the
    # same date index as the input, so it lines up correctly.
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
    pct_below = df["pct_below_sma20"].to_numpy()  # dip signal, same as the rule-based version above
    close = df["Close"].to_numpy()                # actual prices, needed to track real profit/loss
    position = np.zeros(len(df))
    holding = False
    entry_price = None  # the price we "bought" at, once holding - None means not holding anything

    for i in range(len(df)):
        pb = pct_below[i]
        price = close[i]
        if np.isnan(pb):
            position[i] = 0.0
            continue
        if not holding:
            # Not holding - only decision available is whether to buy.
            if pb <= dip_threshold:
                holding = True
                entry_price = price  # remember what we paid, so profit/loss can be measured later
        else:
            # Holding - measure how far price has moved from the actual
            # entry price (not from the moving average) as a fraction.
            gain = price / entry_price - 1.0
            if gain >= profit_target or gain <= -stop_loss:
                # Either the profit target or the stop-loss has been
                # crossed - sell either way, whichever happened first.
                holding = False
                entry_price = None  # clear it - nothing to compare against until the next buy
        position[i] = 1.0 if holding else 0.0

    return pd.Series(position, index=df.index)


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
    middle = close.rolling(bb_window).mean()      # the "middle band" - just a plain moving average
    std = close.rolling(bb_window).std()           # how much price has been bouncing around that average
    upper = middle + bb_std * std                  # middle band, pushed up by bb_std standard deviations
    trend = close.rolling(trend_window).mean()      # a much longer-term average, used to confirm the trend

    # Convert everything to plain arrays once, up front, rather than
    # repeatedly indexing into pandas Series inside the loop below -
    # meaningfully faster for a loop that runs once per bar.
    close_v = close.to_numpy()
    upper_v = upper.to_numpy()
    middle_v = middle.to_numpy()
    trend_v = trend.to_numpy()

    position = np.zeros(len(df))
    holding = False
    for i in range(len(df)):
        if np.isnan(upper_v[i]) or np.isnan(trend_v[i]):
            # Not enough history yet for either rolling average (the
            # long trend_window one especially can take a while to
            # "warm up") - stay flat until both are available.
            position[i] = 0.0
            continue
        if not holding and close_v[i] > upper_v[i] and close_v[i] > trend_v[i]:
            # Breaking out above the upper band AND above the long-term
            # trend - buy into the breakout.
            holding = True
        elif holding and close_v[i] < middle_v[i]:
            # Price has fallen back through the middle band - the
            # breakout has lost steam, sell.
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
    pct_below = df["pct_below_sma20"].to_numpy()  # same dip signal as the rule-based version
    feats = df[FEATURE_COLUMNS]                    # just the columns the model was trained on
    # A row is only usable for prediction if none of its feature columns
    # are missing (e.g. early bars before rolling windows have "warmed
    # up" will have NaNs) - this marks which rows qualify.
    valid = ~feats.isna().any(axis=1)

    # Start every row's model score as NaN ("no prediction"), then fill
    # in real predictions only for the rows that actually have complete
    # feature data.
    scores = np.full(len(df), np.nan)
    if valid.any():
        # predict_proba returns a probability for each class (e.g. "won't
        # bounce" and "will bounce"); [:, 1] takes just the probability
        # of the second class - "will bounce" - which is the number this
        # strategy actually cares about.
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
            # A "dip" by the same rule as before, but only actually
            # acted on if the model is confident enough (its predicted
            # bounce-probability clears the calibrated threshold).
            is_dip = pb <= dip_threshold
            if is_dip and not np.isnan(score) and score >= threshold:
                holding = True
        elif holding and pb >= exit_threshold:
            # Exit rule is identical to the plain rule-based version -
            # the model only ever gets a say in the entry, not the exit.
            holding = False
        position[i] = 1.0 if holding else 0.0

    return pd.Series(position, index=df.index)
