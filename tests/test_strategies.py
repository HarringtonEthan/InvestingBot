"""
Tests for src/strategies.py, in particular day_trading_decision - the
single-step rule factored out so the backtest (dip_buy_profit_target)
and the live trading decision in live_trade.py's decide() both call the
exact same code instead of maintaining two hand-written copies that
could quietly drift apart from each other.
"""

import numpy as np
import pandas as pd
import pytest

from src.strategies import day_trading_decision, dip_buy_profit_target, position_for_params, rule_based_dip_buy


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


def test_rule_based_dip_buy_exits_at_stop_loss_before_recovery():
    # Buys the dip, then keeps falling instead of recovering - with no
    # stop-loss this rule would hold all the way to the end waiting for a
    # recovery that never comes; with one, it should bail out early.
    close = [100, 94, 92, 90, 88, 86]
    # A hand-built pct_below_sma20 series: -6% at the buy bar, then
    # drifting further negative (never recovering back to exit_threshold).
    pct_below = [0.0, -0.06, -0.08, -0.10, -0.12, -0.14]
    df = pd.DataFrame({"Close": close, "pct_below_sma20": pct_below})

    no_stop = rule_based_dip_buy(df, dip_threshold=-0.05, exit_threshold=0.0)
    # No stop-loss: once bought, stays in for the rest of the series -
    # nothing here ever recovers back to exit_threshold.
    assert (no_stop.iloc[1:] == 1.0).all()

    # Entry price is 94 (the bar the dip first crosses -5%). A 5%
    # stop-loss trips once price falls to 94 * 0.95 = 89.3, i.e. bar 88 -
    # sold there (index 4), then immediately re-bought at index 5 since
    # the dip is still (even more) below dip_threshold, same re-entry
    # behavior dip_buy_profit_target already has.
    with_stop = rule_based_dip_buy(df, dip_threshold=-0.05, exit_threshold=0.0, stop_loss=0.05)
    assert with_stop.tolist() == [0.0, 1.0, 1.0, 1.0, 0.0, 1.0]


def test_rule_based_dip_buy_stop_loss_none_preserves_old_behavior():
    # Omitting stop_loss must give byte-for-byte the same result as before
    # this parameter existed - the whole point of defaulting it to None.
    df = _feature_df()
    with_default = rule_based_dip_buy(df, dip_threshold=-0.02, exit_threshold=0.0)
    explicit_none = rule_based_dip_buy(df, dip_threshold=-0.02, exit_threshold=0.0, stop_loss=None)
    pd.testing.assert_series_equal(with_default, explicit_none)


def _feature_df(seed=5, n=200):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1.5, n))
    sma20 = pd.Series(close).rolling(20).mean()
    pct_below = (close - sma20) / sma20
    return pd.DataFrame({"Close": close, "pct_below_sma20": pct_below})


def test_position_for_params_day_trading_matches_direct_call():
    # optimize.py/walk_forward.py call through position_for_params() instead
    # of dip_buy_profit_target()/rule_based_dip_buy() directly - this is the
    # one place both scripts share, so it needs to actually dispatch to the
    # same result a direct call would give, not a subtly different one.
    df = _feature_df()
    params = {"dip_threshold": -0.02, "profit_target": 0.01, "stop_loss": 0.03}
    dispatched = position_for_params("day_trading", df, params)
    direct = dip_buy_profit_target(df, dip_threshold=-0.02, profit_target=0.01, stop_loss=0.03)
    pd.testing.assert_series_equal(dispatched, direct)


def test_position_for_params_rule_based_matches_direct_call():
    df = _feature_df()
    params = {"dip_threshold": -0.02, "exit_threshold": 0.0}
    dispatched = position_for_params("rule_based", df, params)
    direct = rule_based_dip_buy(df, dip_threshold=-0.02, exit_threshold=0.0)
    pd.testing.assert_series_equal(dispatched, direct)


def test_position_for_params_rule_based_with_stop_loss_matches_direct_call():
    # stop_loss is optional in the rule_based params dict - confirm the
    # dispatch actually passes it through, not just silently dropping it.
    df = _feature_df()
    params = {"dip_threshold": -0.02, "exit_threshold": 0.0, "stop_loss": 0.03}
    dispatched = position_for_params("rule_based", df, params)
    direct = rule_based_dip_buy(df, dip_threshold=-0.02, exit_threshold=0.0, stop_loss=0.03)
    pd.testing.assert_series_equal(dispatched, direct)


def test_position_for_params_rejects_unknown_strategy():
    with pytest.raises(ValueError):
        position_for_params("bollinger_breakout", _feature_df(), {})
