"""
Tests for src/model.py, focused on the label-leakage bug that was
previously present: rows without enough future data to know the real
answer used to get labeled 0.0 (a confident "didn't bounce") instead of
NaN (unknown, correctly excluded from training).
"""

import numpy as np
import pandas as pd

from src.model import build_labels


def test_incomplete_lookahead_rows_are_nan_not_zero():
    close = pd.Series(np.linspace(100, 110, 30))
    df = pd.DataFrame({"Close": close})
    labels = build_labels(df, horizon=10, bounce_pct=0.03)
    # The last (horizon - 1) rows don't have a full lookahead window -
    # they must be NaN, never a confident 0.0 or 1.0.
    assert labels.tail(9).isna().all()


def test_rows_with_full_lookahead_are_never_nan():
    close = pd.Series(np.linspace(100, 110, 30))
    df = pd.DataFrame({"Close": close})
    labels = build_labels(df, horizon=10, bounce_pct=0.03)
    # Every row that DOES have a full lookahead window should have a
    # real, defined label - only the tail should be NaN.
    assert labels.iloc[:20].notna().all()


def test_a_real_bounce_is_labeled_1():
    # Price is flat, then jumps well above the bounce threshold within
    # the lookahead window - should be labeled a confirmed bounce.
    close = pd.Series([100.0] * 5 + [110.0] * 10)
    df = pd.DataFrame({"Close": close})
    labels = build_labels(df, horizon=5, bounce_pct=0.03)
    assert labels.iloc[0] == 1.0


def test_no_bounce_within_window_is_labeled_0():
    # Price never moves - no bounce ever happens within the window.
    close = pd.Series([100.0] * 20)
    df = pd.DataFrame({"Close": close})
    labels = build_labels(df, horizon=5, bounce_pct=0.03)
    assert labels.iloc[0] == 0.0
