"""
Tests for visualize_log.py's --baseline-since / filter_equity_since():
panel 1 should only plot the timeline from a given moment forward (e.g.
an account reset), not every row --equity-log happens to have - most of
which predate whatever --baseline is actually meant to measure from.
"""

import pandas as pd

from visualize_log import filter_equity_since


def _equity_df(timestamps, values):
    return pd.DataFrame({
        "timestamp_utc": pd.to_datetime(timestamps, utc=True),
        "portfolio_value_usd": values,
    })


def test_drops_rows_before_the_cutoff():
    df = _equity_df(
        ["2026-07-28T07:00:00+00:00", "2026-07-28T12:00:00+00:00", "2026-07-28T18:15:51+00:00", "2026-07-28T18:20:00+00:00"],
        [99787.08, 99750.00, 99747.83, 99748.10],
    )
    result = filter_equity_since(df, "2026-07-28T18:15:51+00:00")
    assert len(result) == 2
    assert result["portfolio_value_usd"].tolist() == [99747.83, 99748.10]


def test_keeps_row_exactly_at_the_cutoff():
    df = _equity_df(["2026-07-28T18:15:51+00:00"], [99747.83])
    result = filter_equity_since(df, "2026-07-28T18:15:51+00:00")
    assert len(result) == 1


def test_none_input_stays_none():
    assert filter_equity_since(None, "2026-07-28T18:15:51+00:00") is None


def test_every_row_before_cutoff_returns_none():
    # Same "genuinely nothing to plot" signal as a missing/empty log file -
    # not an empty DataFrame, which downstream code isn't set up to handle.
    df = _equity_df(["2026-07-28T07:00:00+00:00"], [99787.08])
    result = filter_equity_since(df, "2026-07-29T00:00:00+00:00")
    assert result is None
