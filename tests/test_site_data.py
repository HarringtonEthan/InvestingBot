"""
Tests for site_data.py - the JSON generator behind the casino dashboard
website (site/). Covers the pieces that are easy to get subtly wrong:
order-status classification (the only three categories this project's
logs can honestly support), period-boundary math in Eastern Time,
realized P&L only ever coming from confirmed fills, and graceful
behavior when a log is empty, missing a column, or has duplicate rows.
"""

import datetime as dt

import pandas as pd
import pytest

from site_data import (
    ET,
    _equity_value_asof,
    _max_drawdown,
    attribute_position_strategy,
    build_positions_payload,
    classify_order_status,
    dedupe_trades,
    period_bounds,
    summarize_period,
)


def _trade_row(**overrides):
    row = {
        "timestamp_utc": pd.Timestamp("2026-07-28T15:00:00+00:00"),
        "mode": "PAPER",
        "asset_class": "stock",
        "ticker": "AAPL",
        "strategy": "rule_based",
        "action": "BUY",
        "price_usd": 100.0,
        "notional_usd": 2000.0,
        "position_qty_before": 0.0,
        "avg_entry_price_usd": "",
        "unrealized_gain_pct": "",
        "order_placed": "True",
        "notes": "",
    }
    row.update(overrides)
    return pd.Series(row)


def _trades_df(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame([dict(_trade_row(**r)) for r in rows])
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    return df


def _equity_df(pairs: list[tuple[str, float]]) -> pd.DataFrame:
    return pd.DataFrame({
        "timestamp_utc": pd.to_datetime([p[0] for p in pairs], utc=True),
        "portfolio_value_usd": [p[1] for p in pairs],
    })


# ---- classify_order_status ----

def test_not_placed_when_order_placed_is_false():
    row = _trade_row(order_placed="False")
    assert classify_order_status(row) == "not_placed"


def test_submitted_unconfirmed_when_notes_say_so():
    row = _trade_row(order_placed="True", notes="Fill not confirmed within the polling window.")
    assert classify_order_status(row) == "submitted_unconfirmed"


def test_confirmed_fill_is_the_default_placed_case():
    row = _trade_row(order_placed="True", notes="")
    assert classify_order_status(row) == "confirmed_fill"


def test_order_placed_read_as_string_not_python_bool():
    # csv.DictWriter writes Python's str(bool) - "True"/"False" strings,
    # never a real bool - classify_order_status must compare as a string.
    row = _trade_row(order_placed="False", notes="")
    assert classify_order_status(row) == "not_placed"


# ---- dedupe_trades ----

def test_dedupe_drops_exact_duplicate_rows():
    df = _trades_df([{}, {}])  # two identical default rows
    result = dedupe_trades(df)
    assert len(result) == 1


def test_dedupe_keeps_distinct_rows():
    df = _trades_df([{"ticker": "AAPL"}, {"ticker": "QQQ"}])
    result = dedupe_trades(df)
    assert len(result) == 2


def test_dedupe_handles_none_and_empty():
    assert dedupe_trades(None) is None
    empty = _trades_df([{}]).iloc[0:0]
    assert dedupe_trades(empty).empty


# ---- period_bounds (daily/weekly/monthly boundaries in ET) ----

def test_today_boundary_is_midnight_et_converted_to_utc():
    # 2026-07-28 15:00 UTC is 11:00 ET (EDT, UTC-4) on 2026-07-28 -
    # midnight ET that same day is 2026-07-28T04:00:00+00:00.
    now = dt.datetime(2026, 7, 28, 15, 0, tzinfo=dt.timezone.utc)
    bounds = period_bounds(now)
    start, end = bounds["today"]
    assert start == dt.datetime(2026, 7, 28, 4, 0, tzinfo=dt.timezone.utc)
    assert end == now


def test_week_boundary_starts_on_monday_et():
    # 2026-07-28 is a Tuesday - the week should start on Monday 2026-07-27.
    now = dt.datetime(2026, 7, 28, 15, 0, tzinfo=dt.timezone.utc)
    bounds = period_bounds(now)
    start, _ = bounds["week"]
    start_et = start.astimezone(ET)
    assert start_et.weekday() == 0  # Monday
    assert start_et.date() == dt.date(2026, 7, 27)


def test_month_boundary_starts_on_the_1st_et():
    now = dt.datetime(2026, 7, 28, 15, 0, tzinfo=dt.timezone.utc)
    bounds = period_bounds(now)
    start, _ = bounds["month"]
    start_et = start.astimezone(ET)
    assert start_et.day == 1
    assert start_et.month == 7


def test_week_boundary_handles_a_monday_itself():
    # 2026-07-27 is itself a Monday - the week should start on that same day.
    now = dt.datetime(2026, 7, 27, 15, 0, tzinfo=dt.timezone.utc)
    bounds = period_bounds(now)
    start, _ = bounds["week"]
    assert start.astimezone(ET).date() == dt.date(2026, 7, 27)


# ---- _equity_value_asof ----

def test_equity_value_asof_returns_last_row_at_or_before_ts():
    df = _equity_df([
        ("2026-07-28T10:00:00+00:00", 100.0),
        ("2026-07-28T12:00:00+00:00", 105.0),
        ("2026-07-28T14:00:00+00:00", 103.0),
    ])
    ts = pd.Timestamp("2026-07-28T13:00:00+00:00")
    assert _equity_value_asof(df, ts) == 105.0


def test_equity_value_asof_none_when_nothing_logged_yet():
    df = _equity_df([("2026-07-28T14:00:00+00:00", 100.0)])
    ts = pd.Timestamp("2026-07-28T04:00:00+00:00")
    assert _equity_value_asof(df, ts) is None


def test_equity_value_asof_none_on_missing_data():
    assert _equity_value_asof(None, pd.Timestamp.now(tz="UTC")) is None
    assert _equity_value_asof(_equity_df([]), pd.Timestamp.now(tz="UTC")) is None


# ---- _max_drawdown ----

def test_max_drawdown_finds_the_worst_decline():
    values = [100.0, 110.0, 90.0, 95.0, 120.0]
    # Worst decline is 110 -> 90, a (90-110)/110 = -18.18% drawdown.
    assert _max_drawdown(values) == pytest.approx(-0.18181818, abs=1e-6)


def test_max_drawdown_none_with_fewer_than_two_points():
    assert _max_drawdown([100.0]) is None
    assert _max_drawdown([]) is None


def test_max_drawdown_zero_for_a_monotonic_rise():
    assert _max_drawdown([100.0, 110.0, 120.0]) == 0.0


# ---- summarize_period: percentage return, realized P&L, win/loss, splits ----

def test_percentage_return_calculation():
    equity_df = _equity_df([
        ("2026-07-27T12:00:00+00:00", 100_000.0),
        ("2026-07-28T12:00:00+00:00", 101_000.0),
    ])
    result = summarize_period(
        "All Time", None, dt.datetime(2026, 7, 28, 13, tzinfo=dt.timezone.utc),
        equity_df, None, None, None,
    )
    assert result["pct_return"] == pytest.approx(0.01)
    assert result["dollar_pnl_usd"] == 1000.0


def test_only_confirmed_fills_count_as_realized_pnl():
    trades = _trades_df([
        {"action": "SELL", "price_usd": 110.0, "avg_entry_price_usd": 100.0,
         "position_qty_before": 10.0, "order_placed": "True", "notes": ""},
        {"action": "SELL", "price_usd": 999.0, "avg_entry_price_usd": 1.0,
         "position_qty_before": 10.0, "order_placed": "True",
         "notes": "Fill not confirmed within the polling window."},
        {"action": "SELL", "price_usd": 999.0, "avg_entry_price_usd": 1.0,
         "position_qty_before": 10.0, "order_placed": "False", "notes": ""},
    ])
    trades["order_status"] = trades.apply(classify_order_status, axis=1)
    trades["is_confirmed_sell"] = (trades["action"] == "SELL") & (trades["order_status"] == "confirmed_fill")
    realized = pd.Series(float("nan"), index=trades.index)
    confirmed = trades["is_confirmed_sell"]
    realized[confirmed] = (trades.loc[confirmed, "price_usd"] - trades.loc[confirmed, "avg_entry_price_usd"]) * trades.loc[confirmed, "position_qty_before"]
    trades["realized_pnl_usd"] = realized

    result = summarize_period("Today", None, dt.datetime(2026, 7, 28, 16, tzinfo=dt.timezone.utc), None, trades, None, None)
    # Only the first (confirmed) row counts: (110-100)*10 = 100.
    assert result["realized_pnl_usd"] == 100.0
    assert result["num_trades"] == 1
    assert result["num_unconfirmed"] == 1
    assert result["num_not_placed"] == 1


def test_win_loss_and_win_rate():
    trades = _trades_df([
        {"action": "SELL", "price_usd": 110.0, "avg_entry_price_usd": 100.0, "position_qty_before": 10.0},
        {"action": "SELL", "price_usd": 90.0, "avg_entry_price_usd": 100.0, "position_qty_before": 10.0},
        {"action": "SELL", "price_usd": 120.0, "avg_entry_price_usd": 100.0, "position_qty_before": 10.0},
    ])
    trades["order_status"] = trades.apply(classify_order_status, axis=1)
    trades["is_confirmed_sell"] = trades["action"] == "SELL"
    trades["realized_pnl_usd"] = (trades["price_usd"] - trades["avg_entry_price_usd"]) * trades["position_qty_before"]

    result = summarize_period("Today", None, dt.datetime(2026, 7, 28, 16, tzinfo=dt.timezone.utc), None, trades, None, None)
    assert result["num_trades"] == 3
    assert result["num_wins"] == 2
    assert result["num_losses"] == 1
    assert result["win_rate"] == pytest.approx(2 / 3)
    assert result["best_trade"]["realized_pnl_usd"] == 200.0
    assert result["worst_trade"]["realized_pnl_usd"] == -100.0


def test_stocks_vs_crypto_split_never_mixes_asset_classes():
    trades = _trades_df([
        {"action": "SELL", "asset_class": "stock", "price_usd": 110.0, "avg_entry_price_usd": 100.0, "position_qty_before": 10.0},
        {"action": "SELL", "asset_class": "crypto", "price_usd": 50.0, "avg_entry_price_usd": 40.0, "position_qty_before": 1.0},
    ])
    trades["order_status"] = trades.apply(classify_order_status, axis=1)
    trades["is_confirmed_sell"] = trades["action"] == "SELL"
    trades["realized_pnl_usd"] = (trades["price_usd"] - trades["avg_entry_price_usd"]) * trades["position_qty_before"]

    result = summarize_period("Today", None, dt.datetime(2026, 7, 28, 16, tzinfo=dt.timezone.utc), None, trades, None, None)
    assert result["stocks_vs_crypto"]["stock"]["realized_pnl_usd"] == 100.0
    assert result["stocks_vs_crypto"]["crypto"]["realized_pnl_usd"] == 10.0
    assert result["stocks_vs_crypto"]["stock"]["num_trades"] == 1
    assert result["stocks_vs_crypto"]["crypto"]["num_trades"] == 1


def test_empty_trade_log_produces_zeroed_not_crashed_summary():
    result = summarize_period("Today", None, dt.datetime(2026, 7, 28, 16, tzinfo=dt.timezone.utc), None, None, None, None)
    assert result["num_trades"] == 0
    assert result["realized_pnl_usd"] == 0.0
    assert result["best_trade"] is None
    assert result["has_equity_data"] is False


def test_starting_value_falls_back_to_first_available_when_no_prior_row():
    # Account was reset partway through the day - nothing logged before
    # the period's own calendar start, so the period's starting value
    # should fall back to the first row actually within it, flagged as such.
    equity_df = _equity_df([("2026-07-28T14:00:00+00:00", 99751.68), ("2026-07-28T15:00:00+00:00", 99760.0)])
    start = dt.datetime(2026, 7, 28, 4, 0, tzinfo=dt.timezone.utc)  # midnight ET
    end = dt.datetime(2026, 7, 28, 16, 0, tzinfo=dt.timezone.utc)
    result = summarize_period("Today", start, end, equity_df, None, None, None)
    assert result["starting_value_usd"] == 99751.68
    assert result["starting_value_is_first_available"] is True


def test_trade_log_reset_flag_set_when_earliest_trade_is_after_carried_forward_starting_equity():
    # equity_log.csv is never reset, but trade_log.csv gets archived and
    # restarted fresh on a same-day relaunch - if the carried-forward
    # "starting" equity reaches back before the earliest trade currently
    # on record, some trade history in this window was archived away, so
    # Dollar P&L (equity-based) and Realized/Unrealized P&L (trade-log-
    # based) are describing different eras of the account.
    equity_df = _equity_df([
        ("2026-07-28T04:00:00+00:00", 99787.08),  # true start-of-day, all cash
        ("2026-07-28T19:00:00+00:00", 99780.29),
    ])
    trades = _trades_df([{"action": "BUY", "timestamp_utc": pd.Timestamp("2026-07-28T19:12:52+00:00")}])
    trades["order_status"] = trades.apply(classify_order_status, axis=1)
    trades["is_confirmed_sell"] = trades["action"] == "SELL"
    trades["realized_pnl_usd"] = None

    start = dt.datetime(2026, 7, 28, 4, 0, tzinfo=dt.timezone.utc)
    end = dt.datetime(2026, 7, 28, 20, 0, tzinfo=dt.timezone.utc)
    result = summarize_period("Today", start, end, equity_df, trades, None, None)
    assert result["starting_value_is_first_available"] is False
    assert result["trade_log_reset_during_period"] is True


def test_starting_value_anchors_to_reset_row_not_stale_pre_reset_equity():
    # Mirrors a real relaunch: equity was ~99787 at true midnight, dipped
    # around during earlier (now-archived) trading, came back to 100%
    # cash at the moment of relaunch (99751.68), and only *then* did the
    # first BUY currently on record happen. The period's starting value
    # should be the relaunch's own all-cash reading, not the stale
    # pre-relaunch midnight figure - otherwise Dollar P&L keeps
    # including swings from trades that no longer appear anywhere on
    # the page.
    equity_df = _equity_df([
        ("2026-07-28T04:00:00+00:00", 99787.08),  # true midnight, pre-relaunch
        ("2026-07-28T13:35:00+00:00", 99785.45),  # pre-relaunch trading (now archived)
        ("2026-07-28T18:53:05+00:00", 99751.68),  # relaunch: back to 100% cash
        ("2026-07-28T19:41:00+00:00", 99780.29),  # after the post-relaunch buys
    ])
    trades = _trades_df([{"action": "BUY", "timestamp_utc": pd.Timestamp("2026-07-28T19:12:52+00:00")}])
    trades["order_status"] = trades.apply(classify_order_status, axis=1)
    trades["is_confirmed_sell"] = trades["action"] == "SELL"
    trades["realized_pnl_usd"] = None

    start = dt.datetime(2026, 7, 28, 4, 0, tzinfo=dt.timezone.utc)  # midnight ET
    end = dt.datetime(2026, 7, 28, 20, 0, tzinfo=dt.timezone.utc)
    result = summarize_period("Today", start, end, equity_df, trades, None, None)
    assert result["starting_value_usd"] == 99751.68
    assert result["starting_value_asof_utc"] == "2026-07-28T18:53:05+00:00"
    assert result["ending_value_usd"] == 99780.29
    assert result["dollar_pnl_usd"] == pytest.approx(28.61)
    assert result["trade_log_reset_during_period"] is True
    assert result["starting_value_is_first_available"] is False


def test_trade_log_reset_flag_not_set_when_trades_predate_period_start():
    equity_df = _equity_df([
        ("2026-07-28T04:00:00+00:00", 99787.08),
        ("2026-07-28T19:00:00+00:00", 99780.29),
    ])
    trades = _trades_df([{"action": "BUY", "timestamp_utc": pd.Timestamp("2026-07-27T10:00:00+00:00")}])
    trades["order_status"] = trades.apply(classify_order_status, axis=1)
    trades["is_confirmed_sell"] = trades["action"] == "SELL"
    trades["realized_pnl_usd"] = None

    start = dt.datetime(2026, 7, 28, 4, 0, tzinfo=dt.timezone.utc)
    end = dt.datetime(2026, 7, 28, 20, 0, tzinfo=dt.timezone.utc)
    result = summarize_period("Today", start, end, equity_df, trades, None, None)
    assert result["trade_log_reset_during_period"] is False


# ---- attribute_position_strategy ----

def test_attributes_the_most_recent_buy_with_no_later_sell():
    trades = _trades_df([
        {"ticker": "AAPL", "action": "BUY", "strategy": "rule_based", "timestamp_utc": pd.Timestamp("2026-07-27T12:00:00+00:00")},
        {"ticker": "AAPL", "action": "SELL", "strategy": "rule_based", "timestamp_utc": pd.Timestamp("2026-07-27T14:00:00+00:00")},
        {"ticker": "AAPL", "action": "BUY", "strategy": "ml_filtered", "timestamp_utc": pd.Timestamp("2026-07-28T10:00:00+00:00")},
    ])
    assert attribute_position_strategy(trades, "AAPL") == "ml_filtered"


def test_attribute_returns_none_when_buy_was_already_sold():
    trades = _trades_df([
        {"ticker": "AAPL", "action": "BUY", "strategy": "rule_based", "timestamp_utc": pd.Timestamp("2026-07-27T12:00:00+00:00")},
        {"ticker": "AAPL", "action": "SELL", "strategy": "rule_based", "timestamp_utc": pd.Timestamp("2026-07-27T14:00:00+00:00")},
    ])
    assert attribute_position_strategy(trades, "AAPL") is None


def test_attribute_returns_none_for_unknown_ticker_or_missing_data():
    assert attribute_position_strategy(None, "AAPL") is None
    trades = _trades_df([{"ticker": "QQQ"}])
    assert attribute_position_strategy(trades, "AAPL") is None


# ---- build_positions_payload: missing Alpaca response / not requested ----

def test_positions_payload_not_requested():
    result = build_positions_payload(None, None)
    assert result["available"] is False
    assert result["positions"] == []


def test_positions_payload_alpaca_error_surfaces_reason_not_crash():
    result = build_positions_payload(([], "RuntimeError: no network access"), None)
    assert result["available"] is False
    assert "no network access" in result["reason"]


def test_positions_payload_success_enriches_with_strategy():
    trades = _trades_df([{"ticker": "AAPL", "action": "BUY", "strategy": "rule_based"}])
    positions = [{"symbol": "AAPL", "is_crypto": False, "qty": 5.0}]
    result = build_positions_payload((positions, None), trades)
    assert result["available"] is True
    assert result["positions"][0]["strategy"] == "rule_based"


# ---- missing columns: a log file without the columns this code expects ----

def test_classify_order_status_handles_missing_notes_column():
    row = pd.Series({"order_placed": "True"})  # no "notes" key at all
    assert classify_order_status(row) == "confirmed_fill"


def test_classify_order_status_handles_missing_order_placed_column():
    row = pd.Series({"notes": ""})  # no "order_placed" key at all
    assert classify_order_status(row) == "not_placed"
