"""
Tests for src/features.py, focused on RSI edge cases: a pure uptrend must
show RSI=100 (max bullish), not the neutral fallback of 50.
"""

import numpy as np
import pandas as pd

from src.features import _rsi, add_features


def test_rsi_pure_uptrend_is_100():
    series = pd.Series(np.arange(1, 40, dtype=float))
    rsi = _rsi(series, window=14)
    assert (rsi.tail(5) == 100.0).all()


def test_rsi_pure_downtrend_is_0():
    series = pd.Series(np.arange(40, 1, -1, dtype=float))
    rsi = _rsi(series, window=14)
    assert (rsi.tail(5) == 0.0).all()


def test_rsi_flat_price_is_neutral_50():
    series = pd.Series([50.0] * 40)
    rsi = _rsi(series, window=14)
    assert (rsi.tail(5) == 50.0).all()


def test_rsi_warmup_period_is_neutral_50():
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
