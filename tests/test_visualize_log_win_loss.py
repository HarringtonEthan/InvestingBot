"""
Regression tests for a real bug (confirmed live 2026-07-29, see
CHANGELOG): visualize_log.py's plot_win_loss/plot_cumulative_pnl treated
a confirmed sell with an unrecorded cost basis (realized_pnl_usd == NaN
- see live_trade.py's decide() fix) as a *loss*, since `NaN > 0` is
False in pandas the same as Python. Both trades this bug affected
(XOM, a real +$64.73 win; DIS, a real -$11.95 loss) were silently shown
as 2 losses / 0 wins instead of the honest "unknown P&L" bucket these
tests check for.
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import pandas as pd
import pytest

from visualize_log import plot_cumulative_pnl, plot_win_loss


def _sells(rows: list[dict]) -> pd.DataFrame:
    base = {"ticker": "XXX", "flagged": False, "realized_pnl_usd": float("nan")}
    df = pd.DataFrame([{**base, **r} for r in rows])
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"])
    return df


def _bar_heights_by_label(ax):
    """Maps each bar container's legend label to its list of per-bar heights."""
    out = {}
    for container in ax.containers:
        label = container.get_label()
        out[label] = [b.get_height() for b in container]
    return out


@pytest.fixture(autouse=True)
def _close_figures():
    yield
    plt.close("all")


def test_win_loss_puts_unknown_pnl_in_its_own_bucket_not_loss():
    sells = _sells([
        {"ticker": "XOM", "timestamp_utc": "2026-07-29T13:35:44", "realized_pnl_usd": 64.73},
        {"ticker": "DIS", "timestamp_utc": "2026-07-29T13:35:46", "realized_pnl_usd": float("nan")},
    ])
    fig, ax = plt.subplots()
    plot_win_loss(ax, sells, "Stocks")

    # Tickers are sorted alphabetically - DIS, then XOM.
    heights = _bar_heights_by_label(ax)
    assert heights["Win"] == [0.0, 1.0]  # DIS isn't a win, XOM is
    assert heights["Loss"] == [0.0, 0.0]  # DIS must NOT be counted as a loss
    assert heights["Unknown P&L (no cost basis)"] == [1.0, 0.0]  # DIS goes here instead


def test_win_loss_real_loss_still_counts_as_loss_not_unknown():
    sells = _sells([
        {"ticker": "DIS", "timestamp_utc": "2026-07-29T13:35:46", "realized_pnl_usd": -11.95},
    ])
    fig, ax = plt.subplots()
    plot_win_loss(ax, sells, "Stocks")

    heights = _bar_heights_by_label(ax)
    assert heights["Loss"] == [1.0]
    assert "Unknown P&L (no cost basis)" not in heights  # bucket omitted entirely when empty


def test_win_loss_all_unknown_shows_gray_bars_not_all_losses():
    sells = _sells([
        {"ticker": "XOM", "timestamp_utc": "2026-07-29T13:35:44"},
        {"ticker": "DIS", "timestamp_utc": "2026-07-29T13:35:46"},
    ])
    fig, ax = plt.subplots()
    plot_win_loss(ax, sells, "Stocks")

    heights = _bar_heights_by_label(ax)
    assert heights["Win"] == [0.0, 0.0]
    assert heights["Loss"] == [0.0, 0.0]
    assert heights["Unknown P&L (no cost basis)"] == [1.0, 1.0]


def test_cumulative_pnl_excludes_unknown_but_plots_known():
    sells = _sells([
        {"ticker": "XOM", "timestamp_utc": "2026-07-29T13:35:44", "realized_pnl_usd": 64.73},
        {"ticker": "DIS", "timestamp_utc": "2026-07-29T13:35:46", "realized_pnl_usd": float("nan")},
    ])
    fig, ax = plt.subplots()
    plot_cumulative_pnl(ax, sells, "Stocks")

    # Only one real data line drawn (the known XOM trade) - excludes the
    # y=0 reference line plot_cumulative_pnl always draws via axhline.
    # Its final value must be the real $64.73, not corrupted by the NaN
    # DIS row.
    lines = [ln for ln in ax.get_lines() if not all(v == 0 for v in ln.get_ydata())]
    assert len(lines) == 1
    assert lines[0].get_ydata()[-1] == pytest.approx(64.73)
    # The excluded-unknown note must be present somewhere on the axes.
    texts = " ".join(t.get_text() for t in ax.texts)
    assert "no recorded cost basis" in texts


def test_cumulative_pnl_all_unknown_shows_explanatory_text_not_blank_axis():
    sells = _sells([
        {"ticker": "XOM", "timestamp_utc": "2026-07-29T13:35:44"},
        {"ticker": "DIS", "timestamp_utc": "2026-07-29T13:35:46"},
    ])
    fig, ax = plt.subplots()
    plot_cumulative_pnl(ax, sells, "Stocks")

    assert len(ax.get_lines()) == 0  # nothing plottable - must not silently draw a broken/empty line (not even axhline, since we return early)
    texts = " ".join(t.get_text() for t in ax.texts)
    assert "2 confirmed Stocks sells recorded" in texts
    assert "cost basis" in texts
