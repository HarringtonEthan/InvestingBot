"""
Tests for src/backtest.py, focused on the annualization behavior:
run_backtest() must scale annualized stats correctly for whatever bar
interval it's given (e.g. 5-minute crypto bars have ~105,120 periods/year,
not the 252 that's correct for daily stock bars).
"""

import numpy as np
import pandas as pd

from src.backtest import run_backtest


def _make_price_series(n, freq, seed=1):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    return pd.Series(close, index=pd.date_range("2026-01-01", periods=n, freq=freq))


def test_periods_per_year_changes_annualized_vol():
    close = _make_price_series(500, "5min")
    position = pd.Series(1.0, index=close.index)
    result_daily_assumption = run_backtest(close, position, periods_per_year=252)
    result_5m_assumption = run_backtest(close, position, periods_per_year=105_120)
    assert result_daily_assumption.annualized_vol != result_5m_assumption.annualized_vol
    assert result_5m_assumption.annualized_vol > result_daily_assumption.annualized_vol


def test_default_periods_per_year_is_252():
    close = _make_price_series(300, "1D")
    position = pd.Series(1.0, index=close.index)
    result = run_backtest(close, position)
    result_explicit = run_backtest(close, position, periods_per_year=252)
    assert result.annualized_vol == result_explicit.annualized_vol


def test_total_return_unaffected_by_periods_per_year():
    close = _make_price_series(300, "5min")
    position = pd.Series(1.0, index=close.index)
    r1 = run_backtest(close, position, periods_per_year=252)
    r2 = run_backtest(close, position, periods_per_year=105_120)
    assert r1.total_return == r2.total_return
    assert r1.max_drawdown == r2.max_drawdown
