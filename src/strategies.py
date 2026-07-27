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
        that may not come for a long time, if ever - the same reasoning
        `dip_buy_profit_target`'s stop-loss exists for, added here after
        walk-forward runs on daily stock bars found ticker/window
        drawdowns as deep as -40% while "waiting it out."
      - After a stop-loss exit specifically (not a normal recovery exit),
        refuse to re-buy for `stop_cooldown_bars` bars even if the dip
        condition is still met. Without this, a sustained decline can
        trigger the same stop-loss over and over - buy, stop out, buy
        again immediately since the dip never went away, stop out again -
        turning one long unrealized drawdown into several smaller
        *realized* losses plus extra transaction costs, which is worse
        than what the stop-loss was meant to prevent. Found running a
        real walk-forward validation with a stop-loss but no cooldown:
        SPY's 2019-12-to-2021-08 window went from -3.2% with no stop-loss
        to -27.4% with one, because the stop kept re-triggering through
        the 2020 crash instead of protecting against it.
        `stop_cooldown_bars=0` (the default) preserves the original
        immediate-re-entry behavior.
    """
    # How far below (or above) its own rolling average the price is at
    # each bar - this is the "is it a dip" signal the whole rule runs on.
    pct_below = df["pct_below_sma20"].to_numpy()
    # Actual prices - only needed to measure real gain/loss from the entry
    # price once a stop-loss is in play (the SMA-based exit above doesn't
    # need this at all, same as the original version of this function).
    close = df["Close"].to_numpy()
    # Will hold the final 0.0/1.0 decision for every bar; starts as all
    # zeros (out of the market) and gets filled in as the loop runs.
    position = np.zeros(len(df))
    # Whether we're currently "in" the trade, as the loop steps through
    # time bar by bar - this is the memory that makes the strategy
    # stateful (today's decision depends on yesterday's, not just today's
    # price alone).
    holding = False
    # The price we bought at, once holding - only used by the stop-loss
    # check below; stays None the whole time if stop_loss isn't set.
    entry_price = None
    # How many more bars must pass before a stop-loss-triggered exit is
    # allowed to re-buy - only ever set to something nonzero right after
    # a stop-out, and only if stop_cooldown_bars > 0; a normal recovery
    # exit never touches this.
    cooldown_remaining = 0

    for i in range(len(df)):
        val = pct_below[i]
        if np.isnan(val):
            # Not enough history yet to compute the SMA (e.g. the very
            # first 19 bars, before a 20-period average is even possible)
            # - stay flat rather than guess.
            position[i] = 0.0
            continue
        if not holding:
            if cooldown_remaining > 0:
                # Still serving out the post-stop-loss cooldown - refuse
                # to re-buy this bar no matter how deep the dip is, and
                # count this bar against the cooldown.
                cooldown_remaining -= 1
            elif val <= dip_threshold:
                # Not currently holding, no cooldown in effect, and price
                # has dropped at least dip_threshold below its average -
                # buy.
                holding = True
                entry_price = close[i]
        else:
            recovered = val >= exit_threshold
            # Only ever True if stop_loss was actually given - otherwise
            # this rule exits purely on mean reversion, exactly as before.
            stopped_out = stop_loss is not None and (close[i] / entry_price - 1.0) <= -stop_loss
            if recovered or stopped_out:
                # Either the price recovered back to the exit line, or
                # (if a stop-loss is set) it fell too far first - sell
                # either way, whichever happened first.
                holding = False
                entry_price = None
                if stopped_out and not recovered:
                    # A genuine stop-loss exit (not just a recovery that
                    # happened to also cross the stop line) - start the
                    # re-entry cooldown, if one was requested.
                    cooldown_remaining = stop_cooldown_bars
        # Whatever "holding" ended up as after the checks above, record
        # it as this bar's position: fully in (1.0) or fully out (0.0).
        position[i] = 1.0 if holding else 0.0

    # Wrap the plain numpy array back into a pandas Series, reusing the
    # same date index as the input, so it lines up correctly.
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
    factored out into its own pure function so the backtest
    (`dip_buy_profit_target` below) and the live decision in
    `live_trade.py`'s `decide()` both call this exact same code instead
    of each maintaining their own hand-written copy of the same logic.
    Two copies that happen to agree today can silently drift apart later
    - that's exactly how the earlier `--dip-threshold` bug happened, not
    a hypothetical risk.

    Returns "BUY", "SELL", or "HOLD".
    """
    if not holding:
        # Not holding - the only decision available is whether today's
        # dip is deep enough to buy. A NaN pct_below_sma20 (not enough
        # history yet to compute the rolling average) means "no opinion,"
        # not "buy" - stay flat rather than guess.
        if not np.isnan(pct_below_sma20) and pct_below_sma20 <= dip_threshold:
            return "BUY"
        return "HOLD"
    else:
        # Holding - measure how far price has moved from the actual
        # entry price (not from the moving average) as a fraction.
        gain = current_price / entry_price - 1.0
        if gain >= profit_target or gain <= -stop_loss:
            # Either the profit target or the stop-loss has been
            # crossed - sell either way, whichever happened first.
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
      - Sell once price is `profit_target` above where you bought (a real
        profit, not just "back to normal").
      - Sell at a loss if price falls `stop_loss` below your entry first -
        without this, a strategy that only sells "once it recovers" can
        ride a sustained downtrend indefinitely waiting for a recovery
        that may not come for a long time, if ever.
    Whichever threshold is hit first wins. For backtesting, entry price is
    this bar's close; live trading uses the broker's actual average entry
    price instead (see live_trade.py), which is the real number that
    matters once money is involved - both call `day_trading_decision`
    above for the actual buy/sell/hold rule itself.
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
            # Not enough history yet to compute the SMA - stay flat
            # rather than guess, regardless of the shared decision
            # function (which would only ever get consulted with real,
            # non-NaN data anyway once past this warm-up period).
            position[i] = 0.0
            continue
        action = day_trading_decision(holding, entry_price, price, pb, dip_threshold, profit_target, stop_loss)
        if action == "BUY":
            holding = True
            entry_price = price  # remember what we paid, so profit/loss can be measured later
        elif action == "SELL":
            holding = False
            entry_price = None  # clear it - nothing to compare against until the next buy
        position[i] = 1.0 if holding else 0.0

    return pd.Series(position, index=df.index)


def position_for_params(strategy: str, df: pd.DataFrame, params: dict, model=None, threshold: float | None = None) -> pd.Series:
    """
    Builds a position series for one of the three rule-based/ML strategies
    this project runs live, given its own parameter shape:
      - "day_trading": {"dip_threshold", "profit_target", "stop_loss"}
      - "rule_based": {"dip_threshold", "exit_threshold"}
      - "ml_filtered": {"dip_threshold", "exit_threshold"} + a trained
        `model`/calibrated `threshold` passed in separately (not part of
        `params`, since a model object isn't something optimize.py can
        write to a CSV column the way every other parameter is)
    Exists so optimize.py's grid search and walk_forward.py's validation
    both call through this one dispatch point instead of each keeping
    its own copy of "which strategy takes which parameters" - two copies
    of that mapping drifting apart is exactly how the earlier
    --dip-threshold bug happened (see day_trading_decision above).
    """
    if strategy == "day_trading":
        return dip_buy_profit_target(
            df, dip_threshold=params["dip_threshold"],
            profit_target=params["profit_target"], stop_loss=params["stop_loss"],
        )
    if strategy == "rule_based":
        # Exits on mean reversion (price recovering back above the SMA),
        # not a fixed target - the same shape ml_filtered's model sits on
        # top of. "stop_loss" and "stop_cooldown_bars" are both optional
        # in this params dict (unlike day_trading, where stop_loss is
        # always required) - .get() rather than ["..."] so callers that
        # never pass them (the original shape) still dispatch to the
        # exact same behavior rule_based_dip_buy()'s own defaults give.
        return rule_based_dip_buy(
            df, dip_threshold=params["dip_threshold"], exit_threshold=params["exit_threshold"],
            stop_cooldown_bars=params.get("stop_cooldown_bars", 0),
            stop_loss=params.get("stop_loss"),
        )
    if strategy == "ml_filtered":
        if model is None or threshold is None:
            # A missing model/threshold here means a caller forgot to load
            # one before reaching this dispatch - fail loudly rather than
            # silently falling back to some other strategy's behavior.
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
