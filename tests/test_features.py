"""
Tests for src/features.py, focused on the RSI edge cases that were
previously wrong: a pure uptrend used to show RSI=50 (neutral) instead
of 100 (max bullish), muting the strongest possible signal. These tests
exist specifically so that regression can never silently come back.
"""

import numpy as np
import pandas as pd

from src.features import _rsi, add_features


def test_rsi_pure_uptrend_is_100():
    # Strictly increasing prices - zero losses in any window - should
    # give the maximum RSI reading (100), not the neutral fallback (50).
    series = pd.Series(np.arange(1, 40, dtype=float))
    rsi = _rsi(series, window=14)
    assert (rsi.tail(5) == 100.0).all()


def test_rsi_pure_downtrend_is_0():
    # Strictly decreasing prices - zero gains in any window - should
    # give the minimum RSI reading (0).
    series = pd.Series(np.arange(40, 1, -1, dtype=float))
    rsi = _rsi(series, window=14)
    assert (rsi.tail(5) == 0.0).all()


def test_rsi_flat_price_is_neutral_50():
    # No movement at all - genuinely no directional signal - should
    # fall back to the neutral midpoint.
    series = pd.Series([50.0] * 40)
    rsi = _rsi(series, window=14)
    assert (rsi.tail(5) == 50.0).all()


def test_rsi_warmup_period_is_neutral_50():
    # Before the rolling window has enough history, RSI can't be
    # computed yet - should default to neutral, not NaN or an error.
    series = pd.Series(np.arange(1, 5, dtype=float))
    rsi = _rsi(series, window=14)
    assert (rsi == 50.0).all()


def test_rsi_always_between_0_and_100():
    rng = np.random.default_rng(0)
    series = pd.Series(100 + np.cumsum(rng.normal(0, 1, 500)))
    rsi = _rsi(series, window=14)
    assert rsi.between(0, 100).all()


def test_add_features_produces_expected_columns():
    close = pd.Series(100 + np.arange(60, dtype=float))
    df = pd.DataFrame({"Close": close})
    out = add_features(df)
    for col in ["sma20", "sma50", "pct_below_sma20", "ret1", "ret5", "ret10", "vol10", "vol20", "rsi14", "drawdown20"]:
        assert col in out.columns
