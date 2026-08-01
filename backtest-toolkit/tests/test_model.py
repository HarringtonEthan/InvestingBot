"""
Tests for src/model.py, focused on the label-leakage class of bug: rows
without enough future data to know the real answer must be labeled NaN
(unknown, correctly excluded from training), never a fabricated 0.0.
"""

import numpy as np
import pandas as pd

from src.model import build_labels


def test_incomplete_lookahead_rows_are_nan_not_zero():
    close = pd.Series(np.linspace(100, 110, 30))
    df = pd.DataFrame({"Close": close})
    labels = build_labels(df, horizon=10, bounce_pct=0.03)
    assert labels.tail(9).isna().all()


def test_rows_with_full_lookahead_are_never_nan():
    close = pd.Series(np.linspace(100, 110, 30))
    df = pd.DataFrame({"Close": close})
    labels = build_labels(df, horizon=10, bounce_pct=0.03)
    assert labels.iloc[:20].notna().all()


def test_a_real_bounce_is_labeled_1():
    close = pd.Series([100.0] * 5 + [110.0] * 10)
    df = pd.DataFrame({"Close": close})
    labels = build_labels(df, horizon=5, bounce_pct=0.03)
    assert labels.iloc[0] == 1.0


def test_no_bounce_within_window_is_labeled_0():
    close = pd.Series([100.0] * 20)
    df = pd.DataFrame({"Close": close})
    labels = build_labels(df, horizon=5, bounce_pct=0.03)
    assert labels.iloc[0] == 0.0
