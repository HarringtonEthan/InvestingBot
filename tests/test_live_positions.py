"""
Tests for visualize_log.py's --live-positions support: summing each open
position's unrealized P&L into a crypto total and a stock total (split
by Broker.get_all_positions()'s is_crypto flag), and reconciling panel
1's whole-account number with those live per-asset-class ones by
appending a live equity point to the same timeline.
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from visualize_log import aggregate_unrealized_pnl, append_live_equity_point, plot_positions_table


def test_aggregate_splits_by_asset_class():
    positions = [
        {"symbol": "BTC/USD", "is_crypto": True, "unrealized_pl": 50.0},
        {"symbol": "ETH/USD", "is_crypto": True, "unrealized_pl": -20.0},
        {"symbol": "DIS", "is_crypto": False, "unrealized_pl": 13.47},
        {"symbol": "CAT", "is_crypto": False, "unrealized_pl": -40.95},
    ]
    crypto_total, stock_total = aggregate_unrealized_pnl(positions)
    assert crypto_total == 30.0
    assert round(stock_total, 2) == -27.48


def test_aggregate_empty_positions_returns_zero():
    assert aggregate_unrealized_pnl([]) == (0.0, 0.0)


def test_aggregate_one_asset_class_only():
    positions = [{"symbol": "XOM", "is_crypto": False, "unrealized_pl": 9.29}]
    crypto_total, stock_total = aggregate_unrealized_pnl(positions)
    assert crypto_total == 0.0
    assert round(stock_total, 2) == 9.29


def test_fake_broker_get_all_positions_matches_real_broker_shape():
    from tests.fake_broker import FakeBroker

    broker = FakeBroker()
    broker.buy_notional("BTC/USD", 1000.0, is_crypto=True)
    broker.buy_notional("DIS", 2000.0, is_crypto=False)
    broker.set_unrealized_pl("BTC/USD", True, 25.0)
    broker.set_unrealized_pl("DIS", False, -13.0)

    positions = broker.get_all_positions()
    crypto_total, stock_total = aggregate_unrealized_pnl(positions)
    assert crypto_total == 25.0
    assert stock_total == -13.0


def test_append_live_equity_point_adds_a_newer_row():
    equity_df = pd.DataFrame({
        "timestamp_utc": pd.to_datetime(["2026-07-28T07:05:54+00:00", "2026-07-28T14:50:57+00:00"], utc=True),
        "portfolio_value_usd": [99787.08, 99777.64],
    })
    result = append_live_equity_point(equity_df, live_equity=99768.21)

    assert len(result) == 3
    # The live point is the most recent one and its value is what panel 1
    # should now read as "right now" - not the stale last-logged row.
    assert result["timestamp_utc"].iloc[-1] > equity_df["timestamp_utc"].iloc[-1]
    assert result["portfolio_value_usd"].iloc[-1] == 99768.21


def test_append_live_equity_point_with_no_prior_log():
    # No equity log exists yet at all (e.g. right after a fresh archive) -
    # the live point should still work standalone rather than crashing.
    result = append_live_equity_point(None, live_equity=100000.0)
    assert len(result) == 1
    assert result["portfolio_value_usd"].iloc[0] == 100000.0


def test_positions_table_sorts_by_market_value_descending():
    positions = [
        {"symbol": "XOM", "current_price": 155.37, "qty": 12.878776167,
         "market_value": 2000.98, "unrealized_pl": 0.9855, "unrealized_plpc": 0.00049},
        {"symbol": "DIS", "current_price": 98.26, "qty": 20.40597198,
         "market_value": 2005.09, "unrealized_pl": 5.10, "unrealized_plpc": 0.00255},
        {"symbol": "CAT", "current_price": 828.36, "qty": 2.371145387,
         "market_value": 1964.15, "unrealized_pl": -35.84, "unrealized_plpc": -0.0179},
    ]
    fig, ax = plt.subplots()
    plot_positions_table(ax, positions, "Stocks")

    assert len(ax.tables) == 1
    table = ax.tables[0]
    # Row 0 is the header; largest market value (DIS) should come first.
    assert table[1, 0].get_text().get_text() == "DIS"
    assert table[2, 0].get_text().get_text() == "XOM"
    assert table[3, 0].get_text().get_text() == "CAT"
    plt.close(fig)


def test_positions_table_distinguishes_no_flag_from_no_positions():
    # positions=None (flag never passed) and positions=[] (flag passed,
    # genuinely nothing held) must not render the same message - one
    # says "you didn't ask," the other says "you asked and there's
    # nothing there right now."
    fig, (ax_none, ax_empty) = plt.subplots(2, 1)
    plot_positions_table(ax_none, None, "Crypto")
    plot_positions_table(ax_empty, [], "Crypto")

    none_text = ax_none.texts[0].get_text()
    empty_text = ax_empty.texts[0].get_text()
    assert "--live-positions" in none_text
    assert "--live-positions" not in empty_text
    assert "No open" in empty_text
    plt.close(fig)
