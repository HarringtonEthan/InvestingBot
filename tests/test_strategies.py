"""
Tests for src/strategies.py, in particular day_trading_decision - the
single-step rule factored out so the backtest (dip_buy_profit_target)
and the live trading decision in live_trade.py's decide() both call the
exact same code instead of maintaining two hand-written copies that
could quietly drift apart from each other.
"""

import numpy as np
import pandas as pd

from src.strategies import day_trading_decision, dip_buy_profit_target


def test_buys_on_a_deep_enough_dip():
    action = day_trading_decision(
        holding=False, entry_price=None, current_price=100.0,
        pct_below_sma20=-0.02, dip_threshold=-0.01,
        profit_target=0.01, stop_loss=0.03,
    )
    assert action == "BUY"


def test_holds_on_a_shallow_dip():
    action = day_trading_decision(
        holding=False, entry_price=None, current_price=100.0,
        pct_below_sma20=-0.005, dip_threshold=-0.01,
        profit_target=0.01, stop_loss=0.03,
    )
    assert action == "HOLD"


def test_does_not_buy_on_nan_dip_signal():
    # Not enough history yet to compute the rolling average - should
    # never be mistaken for "buy."
    action = day_trading_decision(
        holding=False, entry_price=None, current_price=100.0,
        pct_below_sma20=float("nan"), dip_threshold=-0.01,
        profit_target=0.01, stop_loss=0.03,
    )
    assert action == "HOLD"


def test_sells_at_profit_target():
    action = day_trading_decision(
        holding=True, entry_price=100.0, current_price=101.5,
        pct_below_sma20=0.0, dip_threshold=-0.01,
        profit_target=0.01, stop_loss=0.03,
    )
    assert action == "SELL"


def test_sells_at_stop_loss():
    action = day_trading_decision(
        holding=True, entry_price=100.0, current_price=96.5,
        pct_below_sma20=0.0, dip_threshold=-0.01,
        profit_target=0.01, stop_loss=0.03,
    )
    assert action == "SELL"


def test_holds_between_target_and_stop():
    action = day_trading_decision(
        holding=True, entry_price=100.0, current_price=100.2,
        pct_below_sma20=0.0, dip_threshold=-0.01,
        profit_target=0.01, stop_loss=0.03,
    )
    assert action == "HOLD"


def _reference_dip_buy_profit_target(df, dip_threshold, profit_target, stop_loss):
    """
    A from-scratch reimplementation, independent of day_trading_decision -
    this is deliberately the exact same logic dip_buy_profit_target used
    to have before the day_trading_decision refactor, kept here only as
    an independent cross-check. If this and the real function ever
    disagree, the refactor broke something.
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
            # Not enough history yet - stay flat, same as the real function.
            position[i] = 0.0
            continue
        if not holding:
            # Not holding - buy if today's dip clears the threshold.
            if pb <= dip_threshold:
                holding = True
                entry_price = price
        else:
            # Holding - sell at either the profit target or the stop loss,
            # whichever is crossed first.
            gain = price / entry_price - 1.0
            if gain >= profit_target or gain <= -stop_loss:
                holding = False
                entry_price = None
        position[i] = 1.0 if holding else 0.0
    return pd.Series(position, index=df.index)


def test_dip_buy_profit_target_matches_reference_implementation():
    rng = np.random.default_rng(3)
    close = 100 + np.cumsum(rng.normal(0, 1.5, 300))
    sma20 = pd.Series(close).rolling(20).mean()
    pct_below = (close - sma20) / sma20
    df = pd.DataFrame({"Close": close, "pct_below_sma20": pct_below})

    result = dip_buy_profit_target(df, dip_threshold=-0.015, profit_target=0.01, stop_loss=0.03)
    reference = _reference_dip_buy_profit_target(df, dip_threshold=-0.015, profit_target=0.01, stop_loss=0.03)
    pd.testing.assert_series_equal(result, reference)


def test_dip_buy_profit_target_never_trades_during_warmup():
    rng = np.random.default_rng(4)
    close = 100 + np.cumsum(rng.normal(0, 1, 60))
    sma20 = pd.Series(close).rolling(20).mean()
    pct_below = (close - sma20) / sma20
    df = pd.DataFrame({"Close": close, "pct_below_sma20": pct_below})
    result = dip_buy_profit_target(df)
    # First 19 rows have no SMA yet (NaN pct_below) - must be flat.
    assert (result.iloc[:19] == 0.0).all()
