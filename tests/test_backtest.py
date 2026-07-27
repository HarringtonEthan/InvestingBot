"""
Tests for src/backtest.py, focused on the annualization bug that was
previously present: run_backtest() always assumed 252 daily bars/year
regardless of the actual bar interval, making annualized stats wrong
for anything intraday (e.g. 5-minute crypto data).
"""

import numpy as np
import pandas as pd

from src.backtest import run_backtest


def _make_price_series(n, freq, seed=1):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    return pd.Series(close, index=pd.date_range("2026-01-01", periods=n, freq=freq))


def test_periods_per_year_changes_annualized_vol():
    # Same exact returns, scored with two different periods_per_year
    # values, must produce different annualized vol - if they didn't,
    # the parameter isn't actually doing anything.
    close = _make_price_series(500, "5min")
    position = pd.Series(1.0, index=close.index)
    result_daily_assumption = run_backtest(close, position, periods_per_year=252)
    result_5m_assumption = run_backtest(close, position, periods_per_year=105_120)
    assert result_daily_assumption.annualized_vol != result_5m_assumption.annualized_vol
    # 5-minute bars have vastly more periods/year than daily bars, so
    # treating them as if they were daily should understate vol a lot.
    assert result_5m_assumption.annualized_vol > result_daily_assumption.annualized_vol


def test_default_periods_per_year_is_252():
    close = _make_price_series(300, "1D")
    position = pd.Series(1.0, index=close.index)
    result = run_backtest(close, position)
    result_explicit = run_backtest(close, position, periods_per_year=252)
    assert result.annualized_vol == result_explicit.annualized_vol


def test_total_return_unaffected_by_periods_per_year():
    # total_return and max_drawdown aren't annualized figures - they
    # should come out identical regardless of periods_per_year.
    close = _make_price_series(300, "5min")
    position = pd.Series(1.0, index=close.index)
    r1 = run_backtest(close, position, periods_per_year=252)
    r2 = run_backtest(close, position, periods_per_year=105_120)
    assert r1.total_return == r2.total_return
    assert r1.max_drawdown == r2.max_drawdown
