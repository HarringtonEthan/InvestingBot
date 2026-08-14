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
    DAY_TRADING_DIP_THRESHOLD,
    RULE_BASED_DIP_THRESHOLD,
    RULE_BASED_EXIT_THRESHOLD,
    TICKER_CHART_RANGES,
    TRADE_ROW_COLUMNS,
    TICKER_TRACKER_SMA_PERIODS,
    WATCHED_CRYPTO_TICKERS,
    WATCHED_STOCK_TICKERS,
    _equity_value_asof,
    _max_drawdown,
    _position_ticker,
    _sparkline_closes,
    _thin_points,
    _trade_row_json,
    attribute_position_strategy,
    build_position_sma_indicators,
    build_positions_payload,
    build_strategy_backtest_comparison,
    build_ticker_charts,
    build_ticker_performance,
    build_ticker_tracker,
    classify_order_status,
    dedupe_trades,
    find_account_relaunch,
    period_bounds,
    position_entry_timestamp,
    reconcile_unconfirmed_fills,
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


def _equity_df_with_cash(rows: list[tuple[str, float, float]]) -> pd.DataFrame:
    """Same as _equity_df but each row also carries a cash_usd value -
    needed for find_account_relaunch, which reads cash_usd directly."""
    return pd.DataFrame({
        "timestamp_utc": pd.to_datetime([r[0] for r in rows], utc=True),
        "portfolio_value_usd": [r[1] for r in rows],
        "cash_usd": [r[2] for r in rows],
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


# ---- find_account_relaunch ----

def test_find_account_relaunch_picks_latest_full_cash_row():
    # Two full-cash points (100% cash, zero open positions) - the later
    # one is the account's current relaunch, not the first one ever logged.
    df = _equity_df_with_cash([
        ("2026-07-25T07:00:00+00:00", 100000.0, 100000.0),  # earlier reset
        ("2026-07-28T14:00:00+00:00", 99769.29, 93787.11),  # mid-session, positions open
        ("2026-07-28T18:53:05+00:00", 99751.68, 99751.68),  # the real relaunch
        ("2026-07-28T19:12:58+00:00", 99751.00, 91751.72),  # positions bought back
    ])
    result = find_account_relaunch(df)
    assert result is not None
    ts, value = result
    assert ts == pd.Timestamp("2026-07-28T18:53:05+00:00")
    assert value == 99751.68


def test_find_account_relaunch_none_without_cash_column():
    df = _equity_df([("2026-07-28T14:00:00+00:00", 99769.29)])
    assert find_account_relaunch(df) is None


def test_find_account_relaunch_none_when_never_fully_cash():
    df = _equity_df_with_cash([
        ("2026-07-28T14:00:00+00:00", 99769.29, 93787.11),
        ("2026-07-28T19:00:00+00:00", 99751.00, 91751.72),
    ])
    assert find_account_relaunch(df) is None


def test_find_account_relaunch_none_on_empty_or_missing_df():
    assert find_account_relaunch(None) is None
    assert find_account_relaunch(_equity_df_with_cash([]).iloc[0:0]) is None


def test_find_account_relaunch_ignores_full_cash_after_trading_already_began():
    # Real incident, 2026-08-14: the account closed its very last open
    # position (fully cash again for the first time since the real
    # relaunch) - that must NOT be mistaken for a fresh relaunch, or All
    # Time/This Week/This Month all collapse to that instant and weeks
    # of real trade history vanish from every stat while the CSVs
    # themselves stay completely intact.
    equity = _equity_df_with_cash([
        ("2026-07-28T07:05:54+00:00", 99787.08, 99787.08),  # pre-relaunch blip
        ("2026-07-28T18:53:05+00:00", 99751.68, 99751.68),  # the real relaunch
        ("2026-07-28T19:12:58+00:00", 99751.00, 91751.72),  # positions bought back
        ("2026-08-14T13:35:46+00:00", 100038.42, 100038.42),  # last position sold - NOT a relaunch
    ])
    trades = _trades_df([
        {"timestamp_utc": "2026-07-28T19:12:52+00:00", "ticker": "QQQ", "action": "BUY"},
        {"timestamp_utc": "2026-08-14T13:35:46+00:00", "ticker": "AAPL", "action": "SELL"},
    ])
    result = find_account_relaunch(equity, trades)
    assert result is not None
    ts, value = result
    assert ts == pd.Timestamp("2026-07-28T18:53:05+00:00")
    assert value == 99751.68


def test_find_account_relaunch_without_trades_df_keeps_old_unbounded_behavior():
    # No trades_df given (e.g. a brand-new account with nothing logged
    # yet) - falls back to "latest fully-cash row across the whole
    # equity log," same as before trades_df existed as a parameter.
    df = _equity_df_with_cash([
        ("2026-07-25T07:00:00+00:00", 100000.0, 100000.0),
        ("2026-07-28T18:53:05+00:00", 99751.68, 99751.68),
    ])
    ts, value = find_account_relaunch(df)
    assert ts == pd.Timestamp("2026-07-28T18:53:05+00:00")


# ---- period_bounds relaunch floor ----

def test_period_bounds_floors_calendar_start_at_relaunch():
    # Relaunch happened mid-afternoon on the same day "now" is - the
    # calendar month/week/today boundaries (midnight ET, the 1st, ...)
    # would otherwise reach back before it and pull in pre-relaunch
    # history, which is exactly the bug this floor exists to prevent.
    now = dt.datetime(2026, 7, 28, 23, 0, tzinfo=dt.timezone.utc)  # 7pm ET
    relaunch = dt.datetime(2026, 7, 28, 18, 53, 5, tzinfo=dt.timezone.utc)  # 2:53pm ET
    bounds = period_bounds(now, relaunch)
    for period in ("today", "week", "month"):
        start, _ = bounds[period]
        assert start == relaunch, f"{period} should be floored at the relaunch"


def test_period_bounds_relaunch_floor_is_noop_once_calendar_moves_past_it():
    # A day later, midnight ET naturally falls after the relaunch - the
    # floor should do nothing and normal calendar semantics apply.
    now = dt.datetime(2026, 7, 29, 15, 0, tzinfo=dt.timezone.utc)  # 11am ET, next day
    relaunch = dt.datetime(2026, 7, 28, 18, 53, 5, tzinfo=dt.timezone.utc)
    bounds = period_bounds(now, relaunch)
    start, _ = bounds["today"]
    assert start == dt.datetime(2026, 7, 29, 4, 0, tzinfo=dt.timezone.utc)  # midnight ET 7/29
    # week/month still contain the relaunch, so they stay floored at it.
    assert bounds["week"][0] == relaunch
    assert bounds["month"][0] == relaunch


def test_period_bounds_without_relaunch_is_unaffected():
    now = dt.datetime(2026, 7, 28, 15, 0, tzinfo=dt.timezone.utc)
    assert period_bounds(now) == period_bounds(now, None)


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


def test_all_losing_trades_have_no_best_trade():
    # A day with only losses (e.g. a single losing CAT sell) must not
    # show that loss as "Best Trade" too - there's no real winner to
    # report, so best_trade should be None while worst_trade still names
    # the real loss.
    trades = _trades_df([
        {"ticker": "CAT", "action": "SELL", "price_usd": 90.0, "avg_entry_price_usd": 100.0, "position_qty_before": 10.0},
    ])
    trades["order_status"] = trades.apply(classify_order_status, axis=1)
    trades["is_confirmed_sell"] = trades["action"] == "SELL"
    trades["realized_pnl_usd"] = (trades["price_usd"] - trades["avg_entry_price_usd"]) * trades["position_qty_before"]

    result = summarize_period("Today", None, dt.datetime(2026, 7, 28, 16, tzinfo=dt.timezone.utc), None, trades, None, None)
    assert result["num_trades"] == 1
    assert result["best_trade"] is None
    assert result["worst_trade"]["ticker"] == "CAT"
    assert result["worst_trade"]["realized_pnl_usd"] == -100.0


def test_all_winning_trades_have_no_worst_trade():
    # Mirror case: a day with only wins should not show one of those
    # wins as "Worst Trade" either.
    trades = _trades_df([
        {"ticker": "AAPL", "action": "SELL", "price_usd": 110.0, "avg_entry_price_usd": 100.0, "position_qty_before": 10.0},
    ])
    trades["order_status"] = trades.apply(classify_order_status, axis=1)
    trades["is_confirmed_sell"] = trades["action"] == "SELL"
    trades["realized_pnl_usd"] = (trades["price_usd"] - trades["avg_entry_price_usd"]) * trades["position_qty_before"]

    result = summarize_period("Today", None, dt.datetime(2026, 7, 28, 16, tzinfo=dt.timezone.utc), None, trades, None, None)
    assert result["num_trades"] == 1
    assert result["best_trade"]["ticker"] == "AAPL"
    assert result["worst_trade"] is None


def test_confirmed_sell_with_no_computable_pnl_does_not_crash_best_worst():
    # Regression test for a real production crash (2026-07-29, see
    # CHANGELOG): a confirmed SELL whose avg_entry_price_usd came back
    # blank (live_trade.py once only fetched the cost basis for the
    # day_trading strategy - see live_trade.py's decide()) has a NaN
    # realized_pnl_usd. idxmax()/idxmin() raise ValueError on an
    # all-NaN column instead of just skipping it, which took down the
    # entire scheduled site_data.py run. Must still count as a trade,
    # just excluded from best/worst-trade ranking.
    trades = _trades_df([
        {"action": "SELL", "price_usd": 158.53, "avg_entry_price_usd": "", "position_qty_before": 13.02},
    ])
    trades["order_status"] = trades.apply(classify_order_status, axis=1)
    trades["is_confirmed_sell"] = trades["action"] == "SELL"
    realized = pd.Series(float("nan"), index=trades.index)
    confirmed = trades["is_confirmed_sell"]
    realized[confirmed] = (
        pd.to_numeric(trades.loc[confirmed, "price_usd"])
        - pd.to_numeric(trades.loc[confirmed, "avg_entry_price_usd"], errors="coerce")
    ) * trades.loc[confirmed, "position_qty_before"]
    trades["realized_pnl_usd"] = realized

    result = summarize_period("Today", None, dt.datetime(2026, 7, 29, 16, tzinfo=dt.timezone.utc), None, trades, None, None)
    assert result["num_trades"] == 1
    assert result["best_trade"] is None
    assert result["worst_trade"] is None
    assert result["num_wins"] == 0
    assert result["num_losses"] == 0


def test_confirmed_sell_with_unknown_pnl_does_not_hide_a_real_win():
    # A mix of one unknown-P&L sell and one real win - idxmax/idxmin
    # must still find the real winner instead of being confused by the
    # NaN row sitting alongside it.
    trades = _trades_df([
        {"action": "SELL", "price_usd": 110.0, "avg_entry_price_usd": "", "position_qty_before": 10.0},
        {"action": "SELL", "price_usd": 110.0, "avg_entry_price_usd": 100.0, "position_qty_before": 10.0},
    ])
    trades["order_status"] = trades.apply(classify_order_status, axis=1)
    trades["is_confirmed_sell"] = trades["action"] == "SELL"
    realized = pd.Series(float("nan"), index=trades.index)
    confirmed = trades["is_confirmed_sell"]
    realized[confirmed] = (
        pd.to_numeric(trades.loc[confirmed, "price_usd"])
        - pd.to_numeric(trades.loc[confirmed, "avg_entry_price_usd"], errors="coerce")
    ) * trades.loc[confirmed, "position_qty_before"]
    trades["realized_pnl_usd"] = realized

    result = summarize_period("Today", None, dt.datetime(2026, 7, 29, 16, tzinfo=dt.timezone.utc), None, trades, None, None)
    assert result["num_trades"] == 2
    assert result["best_trade"]["realized_pnl_usd"] == 100.0
    # The only trade with a known P&L is a win - there's no real loser to
    # report, so worst_trade must stay None rather than double-labeling
    # that same win as the "worst" trade too.
    assert result["worst_trade"] is None


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


def test_positions_payload_success_enriches_with_strategy_and_bare_ticker(monkeypatch):
    monkeypatch.setattr("src.alpaca_data.get_stock_bars_range", lambda *a, **k: _daily_bars(30))
    trades = _trades_df([{"ticker": "AAPL", "action": "BUY", "strategy": "rule_based"}])
    positions = [{"symbol": "AAPL", "is_crypto": False, "qty": 5.0}]
    result = build_positions_payload((positions, None), trades)
    assert result["available"] is True
    assert result["positions"][0]["strategy"] == "rule_based"
    assert result["positions"][0]["ticker"] == "AAPL"
    # Card sparkline: a real rolling-20-bar-average series computed from
    # the (mocked) bars fetch, not a fabricated/flat one.
    assert len(result["positions"][0]["spark"]) >= 2


def test_positions_payload_crypto_strategy_matches_via_bare_ticker(monkeypatch):
    # Alpaca's positions endpoint returns crypto symbols without a slash
    # ("BTCUSD"), but the trade log's own "ticker" column is always the
    # bare form live_trade.py's --ticker CLI arg uses ("BTC") - without
    # converting first, every crypto position's strategy silently came
    # back "unknown" even when the trade log clearly showed day_trading.
    monkeypatch.setattr("src.alpaca_data.get_crypto_bars_range", lambda *a, **k: _daily_bars(30, start_price=60000.0, step=50.0))
    trades = _trades_df([{"ticker": "BTC", "asset_class": "crypto", "action": "BUY", "strategy": "day_trading"}])
    positions = [{"symbol": "BTCUSD", "is_crypto": True, "qty": 0.1}]
    result = build_positions_payload((positions, None), trades)
    assert result["positions"][0]["ticker"] == "BTC"
    assert result["positions"][0]["strategy"] == "day_trading"


def test_positions_payload_spark_fetch_failure_does_not_block_position(monkeypatch):
    def fail_if_called(*a, **k):
        raise RuntimeError("no network access")
    monkeypatch.setattr("src.alpaca_data.get_stock_bars_range", fail_if_called)
    trades = _trades_df([{"ticker": "AAPL", "action": "BUY", "strategy": "rule_based"}])
    positions = [{"symbol": "AAPL", "is_crypto": False, "qty": 5.0}]
    result = build_positions_payload((positions, None), trades)
    assert result["available"] is True
    assert result["positions"][0]["spark"] == []


# ---- missing columns: a log file without the columns this code expects ----

def test_classify_order_status_handles_missing_notes_column():
    row = pd.Series({"order_placed": "True"})  # no "notes" key at all
    assert classify_order_status(row) == "confirmed_fill"


def test_classify_order_status_handles_missing_order_placed_column():
    row = pd.Series({"notes": ""})  # no "order_placed" key at all
    assert classify_order_status(row) == "not_placed"


# ---- position_entry_timestamp: same rule as attribute_position_strategy,
# just returning the timestamp instead of the strategy, so a position
# card's chart start date can never disagree with its strategy label ----

def test_entry_timestamp_is_the_most_recent_unmatched_buy():
    trades = _trades_df([
        {"ticker": "AAPL", "action": "BUY", "timestamp_utc": pd.Timestamp("2026-07-27T12:00:00+00:00")},
        {"ticker": "AAPL", "action": "SELL", "timestamp_utc": pd.Timestamp("2026-07-27T14:00:00+00:00")},
        {"ticker": "AAPL", "action": "BUY", "timestamp_utc": pd.Timestamp("2026-07-28T10:00:00+00:00")},
    ])
    assert position_entry_timestamp(trades, "AAPL") == pd.Timestamp("2026-07-28T10:00:00+00:00")


def test_entry_timestamp_none_when_last_buy_was_already_sold():
    trades = _trades_df([
        {"ticker": "AAPL", "action": "BUY", "timestamp_utc": pd.Timestamp("2026-07-27T12:00:00+00:00")},
        {"ticker": "AAPL", "action": "SELL", "timestamp_utc": pd.Timestamp("2026-07-27T14:00:00+00:00")},
    ])
    assert position_entry_timestamp(trades, "AAPL") is None


def test_entry_timestamp_none_for_unknown_ticker_or_missing_data():
    assert position_entry_timestamp(None, "AAPL") is None
    trades = _trades_df([{"ticker": "QQQ"}])
    assert position_entry_timestamp(trades, "AAPL") is None


# ---- _thin_points: downsamples but always keeps the first and last bar ----

def test_thin_points_keeps_all_when_under_the_cap():
    df = pd.DataFrame({"Close": [1.0, 2.0, 3.0]}, index=pd.date_range("2026-07-01", periods=3, freq="1D", tz="UTC"))
    points = _thin_points(df, max_points=300)
    assert len(points) == 3
    assert points[0]["price"] == 1.0
    assert points[-1]["price"] == 3.0


def test_thin_points_downsamples_but_keeps_first_and_last():
    df = pd.DataFrame({"Close": list(range(1000))}, index=pd.date_range("2026-01-01", periods=1000, freq="5min", tz="UTC"))
    points = _thin_points(df, max_points=50)
    assert len(points) <= 51  # a small, bounded overshoot from always including the last real bar
    assert points[0]["price"] == 0.0
    assert points[-1]["price"] == 999.0


def test_thin_points_empty_input():
    assert _thin_points(None) == []
    assert _thin_points(pd.DataFrame()) == []


# ---- _sparkline_closes: same keep-first-and-last downsampling as
# _thin_points, but bare floats (no timestamps) for a card sparkline.
# Takes a plain Series (build_positions_payload/build_ticker_tracker both
# feed it a rolling-20-bar-average column, not raw price - see those
# functions' own docstrings) rather than a whole OHLC DataFrame. ----

def test_sparkline_closes_keeps_all_when_under_the_cap():
    values = _sparkline_closes(pd.Series([1.0, 2.0, 3.0]), max_points=20)
    assert values == [1.0, 2.0, 3.0]


def test_sparkline_closes_downsamples_but_keeps_first_and_last():
    values = _sparkline_closes(pd.Series([float(i) for i in range(200)]), max_points=20)
    assert len(values) <= 21
    assert values[0] == 0.0
    assert values[-1] == 199.0


def test_sparkline_closes_empty_or_too_short_is_honest_not_a_flat_line():
    assert _sparkline_closes(None) == []
    assert _sparkline_closes(pd.Series([], dtype=float)) == []
    assert _sparkline_closes(pd.Series([1.0])) == []


# ---- build_position_sma_indicators ----

def _rising_bars(n: int, start_price: float = 100.0, step: float = 1.0) -> pd.DataFrame:
    idx = pd.date_range("2026-07-01", periods=n, freq="5min", tz="UTC")
    closes = [start_price + i * step for i in range(n)]
    return pd.DataFrame({"Close": closes}, index=idx)


def test_sma_indicators_not_requested():
    result = build_position_sma_indicators(None, None)
    assert result["available"] is False
    assert result["symbols"] == {}


def test_sma_indicators_alpaca_error_surfaces_reason_not_crash():
    result = build_position_sma_indicators(([], "RuntimeError: no network access"), None)
    assert result["available"] is False
    assert "no network access" in result["reason"]


def test_sma_indicators_no_open_positions():
    result = build_position_sma_indicators(([], None), None)
    assert result["available"] is True
    assert result["symbols"] == {}


def test_sma_indicators_skips_day_trading_positions(monkeypatch):
    trades = _trades_df([{"ticker": "BTCUSD", "action": "BUY", "strategy": "day_trading"}])
    positions = [{"symbol": "BTCUSD", "is_crypto": True}]

    def fail_if_called(*args, **kwargs):
        raise AssertionError("day_trading positions should never need a bars fetch here")

    monkeypatch.setattr("src.alpaca_data.get_crypto_bars_range", fail_if_called)
    result = build_position_sma_indicators((positions, None), trades)
    assert result["available"] is True
    assert result["symbols"] == {}


def test_sma_indicators_computes_pct_vs_sma20_for_rule_based(monkeypatch):
    trades = _trades_df([{"ticker": "AAPL", "action": "BUY", "strategy": "rule_based"}])
    positions = [{"symbol": "AAPL", "is_crypto": False}]

    def fake_stock_bars(symbol, interval, start, end):
        assert symbol == "AAPL"
        return _rising_bars(30)

    monkeypatch.setattr("src.alpaca_data.get_stock_bars_range", fake_stock_bars)
    result = build_position_sma_indicators((positions, None), trades)
    aapl = result["symbols"]["AAPL"]
    assert aapl["available"] is True
    assert aapl["reason"] is None
    # A steadily rising series sits *above* its own trailing average.
    assert aapl["pct_vs_sma20"] > 0
    assert aapl["exit_threshold"] == RULE_BASED_EXIT_THRESHOLD


def test_sma_indicators_ml_filtered_also_included(monkeypatch):
    trades = _trades_df([{"ticker": "AAPL", "action": "BUY", "strategy": "ml_filtered"}])
    positions = [{"symbol": "AAPL", "is_crypto": False}]
    monkeypatch.setattr("src.alpaca_data.get_stock_bars_range", lambda *a, **k: _rising_bars(30))
    result = build_position_sma_indicators((positions, None), trades)
    assert result["symbols"]["AAPL"]["available"] is True


def test_sma_indicators_crypto_symbol_conversion(monkeypatch):
    # The trade log's own "ticker" column is always the bare form
    # live_trade.py's --ticker CLI arg uses ("BTC"), not Alpaca's own
    # positions-endpoint symbol ("BTCUSD") - strategy attribution has to
    # convert before it can match, same as build_positions_payload.
    trades = _trades_df([{"ticker": "BTC", "asset_class": "crypto", "action": "BUY", "strategy": "rule_based"}])
    positions = [{"symbol": "BTCUSD", "is_crypto": True}]

    def fake_crypto_bars(symbol, interval, start, end):
        assert symbol == "BTC/USD"
        return _rising_bars(30, start_price=60000.0, step=100.0)

    monkeypatch.setattr("src.alpaca_data.get_crypto_bars_range", fake_crypto_bars)
    result = build_position_sma_indicators((positions, None), trades)
    assert result["symbols"]["BTCUSD"]["available"] is True


def test_sma_indicators_not_enough_history_is_honest_not_a_guess(monkeypatch):
    trades = _trades_df([{"ticker": "AAPL", "action": "BUY", "strategy": "rule_based"}])
    positions = [{"symbol": "AAPL", "is_crypto": False}]

    # Fewer than 20 bars - rolling(20).mean() is NaN for every row.
    monkeypatch.setattr("src.alpaca_data.get_stock_bars_range", lambda *a, **k: _rising_bars(10))
    result = build_position_sma_indicators((positions, None), trades)
    aapl = result["symbols"]["AAPL"]
    assert aapl["available"] is False
    assert aapl["pct_vs_sma20"] is None
    assert aapl["exit_threshold"] == RULE_BASED_EXIT_THRESHOLD
    assert "not enough" in aapl["reason"]


def test_sma_indicators_per_symbol_failure_does_not_block_others(monkeypatch):
    trades = _trades_df([
        {"ticker": "AAPL", "action": "BUY", "strategy": "rule_based"},
        {"ticker": "MSFT", "action": "BUY", "strategy": "rule_based"},
    ])
    positions = [
        {"symbol": "AAPL", "is_crypto": False},
        {"symbol": "MSFT", "is_crypto": False},
    ]

    def fake_stock_bars(symbol, interval, start, end):
        if symbol == "AAPL":
            raise RuntimeError("Alpaca returned no stock bars for AAPL")
        return _rising_bars(30)

    monkeypatch.setattr("src.alpaca_data.get_stock_bars_range", fake_stock_bars)
    result = build_position_sma_indicators((positions, None), trades)
    assert result["symbols"]["AAPL"]["available"] is False
    assert "no stock bars" in result["symbols"]["AAPL"]["reason"]
    assert result["symbols"]["MSFT"]["available"] is True


# ---- _position_ticker ----

def test_position_ticker_stock_passes_through_unchanged():
    assert _position_ticker("AAPL", is_crypto=False) == "AAPL"


def test_position_ticker_crypto_strips_quote_currency():
    # Alpaca's positions endpoint returns crypto symbols without the "/"
    # (e.g. "BTCUSD") - must become the bare "BTC" live_trade.py actually
    # logs as its ticker, or every trade-log/watched-ticker lookup keyed
    # off a live crypto position would silently and permanently miss.
    assert _position_ticker("BTCUSD", is_crypto=True) == "BTC"


# ---- build_ticker_tracker ----

def _daily_bars(n: int, start_price: float = 100.0, step: float = 1.0) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq="1D", tz="UTC")
    closes = [start_price + i * step for i in range(n)]
    return pd.DataFrame({"Close": closes}, index=idx)


def test_ticker_tracker_not_requested():
    result = build_ticker_tracker(None)
    assert result["available"] is False
    assert result["categories"] == {"stocks": [], "crypto": []}


def test_ticker_tracker_alpaca_error_surfaces_reason_not_crash():
    result = build_ticker_tracker(([], "RuntimeError: no network access"))
    assert result["available"] is False
    assert "no network access" in result["reason"]


def test_ticker_tracker_covers_the_full_watched_universe_alphabetically(monkeypatch):
    monkeypatch.setattr("src.alpaca_data.get_stock_bars_range", lambda *a, **k: _daily_bars(120))
    monkeypatch.setattr("src.alpaca_data.get_crypto_bars_range", lambda *a, **k: _daily_bars(120, start_price=60000.0, step=50.0))
    result = build_ticker_tracker(([], None))
    stock_tickers = [row["ticker"] for row in result["categories"]["stocks"]]
    crypto_tickers = [row["ticker"] for row in result["categories"]["crypto"]]
    # A ticker tracker is for quickly finding one specific ticker -
    # alphabetical, not the workflow's own --ticker list order.
    assert stock_tickers == sorted(WATCHED_STOCK_TICKERS)
    assert crypto_tickers == sorted(WATCHED_CRYPTO_TICKERS)
    assert set(stock_tickers) == set(WATCHED_STOCK_TICKERS)
    assert set(crypto_tickers) == set(WATCHED_CRYPTO_TICKERS)


def test_ticker_tracker_computes_sma100_and_pct(monkeypatch):
    monkeypatch.setattr("src.alpaca_data.get_stock_bars_range", lambda *a, **k: _daily_bars(120))
    result = build_ticker_tracker(([], None))
    aapl = next(row for row in result["categories"]["stocks"] if row["ticker"] == "AAPL")
    assert aapl["available"] is True
    assert aapl["reason"] is None
    # A steadily rising series sits *above* its own trailing average.
    assert aapl["pct_vs_sma100"] > 0
    assert aapl["last_close"] == 219.0  # 100 + 119*1.0


def test_ticker_tracker_spark_plots_the_rolling_20_bar_average(monkeypatch):
    # get_stock_bars_range is also called separately (a different
    # interval, "1d") for the unrelated 100-day SMA reading above - only
    # the "5m" call count matters here, to prove the sparkline reuses
    # the same 20-bar/5-minute df already fetched for pct_vs_sma20 rather
    # than issuing its own second "5m" fetch per ticker.
    calls = {"5m": 0}

    def counting_bars(ticker, interval, start, end):
        if interval == "5m":
            calls["5m"] += 1
        return _daily_bars(120)

    monkeypatch.setattr("src.alpaca_data.get_stock_bars_range", counting_bars)
    result = build_ticker_tracker(([], None))
    aapl = next(row for row in result["categories"]["stocks"] if row["ticker"] == "AAPL")
    # A steadily-rising input series' own rolling average is monotonically
    # non-decreasing - proves this is really the smoothed average, not
    # raw (noisier) price passed straight through.
    assert len(aapl["spark"]) >= 2
    assert all(b >= a for a, b in zip(aapl["spark"], aapl["spark"][1:]))
    assert calls["5m"] == len(WATCHED_STOCK_TICKERS)


def test_ticker_tracker_spark_empty_on_fetch_failure(monkeypatch):
    def fail_if_called(*a, **k):
        raise RuntimeError("no network access")
    monkeypatch.setattr("src.alpaca_data.get_stock_bars_range", fail_if_called)
    result = build_ticker_tracker(([], None))
    aapl = next(row for row in result["categories"]["stocks"] if row["ticker"] == "AAPL")
    assert aapl["available"] is False
    assert aapl["spark"] == []


def test_ticker_tracker_not_enough_history_is_honest_not_a_guess(monkeypatch):
    # Fewer than TICKER_TRACKER_SMA_PERIODS bars - rolling(100).mean() is
    # NaN for every row.
    monkeypatch.setattr("src.alpaca_data.get_stock_bars_range", lambda *a, **k: _daily_bars(TICKER_TRACKER_SMA_PERIODS - 1))
    result = build_ticker_tracker(([], None))
    aapl = next(row for row in result["categories"]["stocks"] if row["ticker"] == "AAPL")
    assert aapl["available"] is False
    assert aapl["sma100"] is None
    assert aapl["pct_vs_sma100"] is None
    assert "not enough" in aapl["reason"]


def test_ticker_tracker_marks_a_held_stock_as_profit_or_loss(monkeypatch):
    monkeypatch.setattr("src.alpaca_data.get_stock_bars_range", lambda *a, **k: _daily_bars(120))
    positions = [
        {"symbol": "AAPL", "is_crypto": False, "unrealized_plpc": 0.05},
        {"symbol": "DIS", "is_crypto": False, "unrealized_plpc": -0.02},
    ]
    result = build_ticker_tracker((positions, None))
    by_ticker = {row["ticker"]: row for row in result["categories"]["stocks"]}
    assert by_ticker["AAPL"]["held"] is True
    assert by_ticker["AAPL"]["position_state"] == "profit"
    assert by_ticker["DIS"]["held"] is True
    assert by_ticker["DIS"]["position_state"] == "loss"
    # Every other watched stock isn't held at all.
    assert by_ticker["QQQ"]["held"] is False
    assert by_ticker["QQQ"]["position_state"] == "not_held"
    assert by_ticker["QQQ"]["unrealized_plpc"] is None


def test_ticker_tracker_matches_a_held_crypto_position_by_bare_ticker(monkeypatch):
    # Positions endpoint returns "BTCUSD" (no slash) - must still match
    # the watched "BTC" row, not silently show it as not held.
    monkeypatch.setattr("src.alpaca_data.get_crypto_bars_range", lambda *a, **k: _daily_bars(120, start_price=60000.0, step=50.0))
    positions = [{"symbol": "BTCUSD", "is_crypto": True, "unrealized_plpc": 0.03}]
    result = build_ticker_tracker((positions, None))
    btc = next(row for row in result["categories"]["crypto"] if row["ticker"] == "BTC")
    assert btc["held"] is True
    assert btc["position_state"] == "profit"


def test_ticker_tracker_thresholds_differ_by_asset_class(monkeypatch):
    monkeypatch.setattr("src.alpaca_data.get_stock_bars_range", lambda *a, **k: _daily_bars(120))
    monkeypatch.setattr("src.alpaca_data.get_crypto_bars_range", lambda *a, **k: _daily_bars(120, start_price=60000.0, step=50.0))
    result = build_ticker_tracker(([], None))
    aapl = next(row for row in result["categories"]["stocks"] if row["ticker"] == "AAPL")
    btc = next(row for row in result["categories"]["crypto"] if row["ticker"] == "BTC")
    assert aapl["dip_threshold"] == RULE_BASED_DIP_THRESHOLD
    assert aapl["exit_threshold"] == RULE_BASED_EXIT_THRESHOLD
    # Crypto's day_trading strategy exits on profit-target/stop-loss
    # against its own entry price, not an SMA20 recovery - no exit_threshold.
    assert btc["dip_threshold"] == DAY_TRADING_DIP_THRESHOLD
    assert btc["exit_threshold"] is None


def test_ticker_tracker_per_ticker_failure_does_not_block_others(monkeypatch):
    def fake_stock_bars(symbol, interval, start, end):
        if symbol == "AAPL":
            raise RuntimeError("Alpaca returned no stock bars for AAPL")
        return _daily_bars(120)

    monkeypatch.setattr("src.alpaca_data.get_stock_bars_range", fake_stock_bars)
    result = build_ticker_tracker(([], None))
    by_ticker = {row["ticker"]: row for row in result["categories"]["stocks"]}
    assert by_ticker["AAPL"]["available"] is False
    assert "no stock bars" in by_ticker["AAPL"]["reason"]
    assert by_ticker["QQQ"]["available"] is True


def test_ticker_tracker_computes_sma20_for_every_ticker_held_or_not(monkeypatch):
    monkeypatch.setattr("src.alpaca_data.get_stock_bars_range", lambda *a, **k: _daily_bars(120))
    result = build_ticker_tracker(([], None))
    aapl = next(row for row in result["categories"]["stocks"] if row["ticker"] == "AAPL")
    assert aapl["held"] is False
    assert aapl["sma20_available"] is True
    assert aapl["sma20_reason"] is None
    assert aapl["sma20"] is not None
    # A steadily rising series sits *above* its own trailing average.
    assert aapl["pct_vs_sma20"] > 0


def test_ticker_tracker_sma20_not_enough_history_is_honest(monkeypatch):
    monkeypatch.setattr("src.alpaca_data.get_stock_bars_range", lambda *a, **k: _daily_bars(10))
    result = build_ticker_tracker(([], None))
    aapl = next(row for row in result["categories"]["stocks"] if row["ticker"] == "AAPL")
    assert aapl["sma20_available"] is False
    assert aapl["sma20"] is None
    assert aapl["pct_vs_sma20"] is None
    assert "not enough" in aapl["sma20_reason"]


def test_ticker_tracker_sma20_failure_does_not_block_sma100(monkeypatch):
    # Only the 20-bar (5m) fetch fails - the independently-fetched
    # 100-day metric must still come through, and vice versa.
    def fake_stock_bars(symbol, interval, start, end):
        if interval == "5m":
            raise RuntimeError("no 5-minute bars available")
        return _daily_bars(120)

    monkeypatch.setattr("src.alpaca_data.get_stock_bars_range", fake_stock_bars)
    result = build_ticker_tracker(([], None))
    aapl = next(row for row in result["categories"]["stocks"] if row["ticker"] == "AAPL")
    assert aapl["available"] is True
    assert aapl["sma20_available"] is False
    assert "no 5-minute bars" in aapl["sma20_reason"]


# ---- build_ticker_charts ----

_INTERVAL_FREQ = {"5m": "5min", "15m": "15min", "1h": "1h", "1d": "1D"}


def _bars_for_interval(interval, start, end):
    """
    A realistic fake bars fetch: builds bars at the *requested* interval
    spanning [start, end], clipped to "now" - close enough to Alpaca's
    real behavior that build_ticker_charts's per-range date-window
    slicing (the part actually under test here) has something real to
    slice against, unlike a fixed-shape fixture that would pass no
    matter what window was requested.
    """
    now = pd.Timestamp.now(tz="UTC")
    idx = pd.date_range(pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC"), freq=_INTERVAL_FREQ[interval], tz="UTC")
    idx = idx[idx <= now]
    return pd.DataFrame({"Close": [100.0 + i * 0.01 for i in range(len(idx))]}, index=idx)


def test_ticker_charts_not_requested():
    result = build_ticker_charts(None)
    assert result["available"] is False
    assert result["symbols"] == {}


def test_ticker_charts_alpaca_error_surfaces_reason_not_crash():
    result = build_ticker_charts(([], "RuntimeError: no network access"))
    assert result["available"] is False
    assert "no network access" in result["reason"]


def test_ticker_charts_covers_the_full_watched_universe(monkeypatch):
    monkeypatch.setattr("src.alpaca_data.get_stock_bars_range", lambda symbol, interval, start, end: _bars_for_interval(interval, start, end))
    monkeypatch.setattr("src.alpaca_data.get_crypto_bars_range", lambda symbol, interval, start, end: _bars_for_interval(interval, start, end))
    result = build_ticker_charts(([], None))
    assert set(result["symbols"].keys()) == set(WATCHED_STOCK_TICKERS) | set(WATCHED_CRYPTO_TICKERS)


def test_ticker_charts_each_range_uses_its_configured_interval(monkeypatch):
    monkeypatch.setattr("src.alpaca_data.get_stock_bars_range", lambda symbol, interval, start, end: _bars_for_interval(interval, start, end))
    result = build_ticker_charts(([], None))
    aapl = result["symbols"]["AAPL"]
    for range_key, cfg in TICKER_CHART_RANGES.items():
        assert aapl["ranges"][range_key]["interval"] == cfg["interval"]


def test_ticker_charts_100d_range_keeps_exactly_the_sma_window(monkeypatch):
    monkeypatch.setattr("src.alpaca_data.get_stock_bars_range", lambda symbol, interval, start, end: _bars_for_interval(interval, start, end))
    result = build_ticker_charts(([], None))
    aapl = result["symbols"]["AAPL"]
    assert len(aapl["ranges"]["100d"]["points"]) == TICKER_TRACKER_SMA_PERIODS
    assert aapl["sma100"] is not None


def test_ticker_charts_1d_range_excludes_bars_older_than_a_day(monkeypatch):
    monkeypatch.setattr("src.alpaca_data.get_stock_bars_range", lambda symbol, interval, start, end: _bars_for_interval(interval, start, end))
    result = build_ticker_charts(([], None))
    points = result["symbols"]["AAPL"]["ranges"]["1d"]["points"]
    assert points  # the 5-day fetch buffer comfortably covers "the last day"
    oldest = pd.Timestamp(points[0]["t"])
    assert (pd.Timestamp.now(tz="UTC") - oldest) <= pd.Timedelta(days=1, hours=1)


def test_ticker_charts_crypto_symbol_conversion(monkeypatch):
    seen_symbols = set()

    def fake_crypto_bars(symbol, interval, start, end):
        seen_symbols.add(symbol)
        return _bars_for_interval(interval, start, end)

    monkeypatch.setattr("src.alpaca_data.get_crypto_bars_range", fake_crypto_bars)
    result = build_ticker_charts(([], None))
    assert result["symbols"]["BTC"]["available"] is True
    assert "BTC/USD" in seen_symbols


def test_ticker_charts_per_range_failure_does_not_block_other_ranges(monkeypatch):
    def fake_stock_bars(symbol, interval, start, end):
        if interval == "5m":
            raise RuntimeError("no 5-minute bars available")
        return _bars_for_interval(interval, start, end)

    monkeypatch.setattr("src.alpaca_data.get_stock_bars_range", fake_stock_bars)
    result = build_ticker_charts(([], None))
    aapl = result["symbols"]["AAPL"]
    assert aapl["available"] is True  # other ranges still came through
    assert aapl["ranges"]["1d"]["available"] is False
    assert "no 5-minute bars" in aapl["ranges"]["1d"]["reason"]
    assert aapl["ranges"]["100d"]["available"] is True


def test_ticker_charts_per_ticker_failure_does_not_block_others(monkeypatch):
    def fake_stock_bars(symbol, interval, start, end):
        if symbol == "AAPL":
            raise RuntimeError("Alpaca returned no bars for AAPL")
        return _bars_for_interval(interval, start, end)

    monkeypatch.setattr("src.alpaca_data.get_stock_bars_range", fake_stock_bars)
    result = build_ticker_charts(([], None))
    assert result["symbols"]["AAPL"]["available"] is False
    assert result["symbols"]["QQQ"]["available"] is True


def test_ticker_charts_marks_a_held_ticker_with_its_real_entry_price(monkeypatch):
    monkeypatch.setattr("src.alpaca_data.get_stock_bars_range", lambda symbol, interval, start, end: _bars_for_interval(interval, start, end))
    positions = [{"symbol": "AAPL", "is_crypto": False, "avg_entry_price": 305.5, "current_price": 306.0, "unrealized_plpc": 0.02}]
    result = build_ticker_charts((positions, None))
    aapl = result["symbols"]["AAPL"]
    assert aapl["held"] is True
    assert aapl["entry_price"] == 305.5
    qqq = result["symbols"]["QQQ"]
    assert qqq["held"] is False
    assert qqq["entry_price"] is None


def test_ticker_charts_matches_a_held_crypto_position_by_bare_ticker(monkeypatch):
    monkeypatch.setattr("src.alpaca_data.get_crypto_bars_range", lambda symbol, interval, start, end: _bars_for_interval(interval, start, end))
    positions = [{"symbol": "BTCUSD", "is_crypto": True, "avg_entry_price": 60000.0, "current_price": 60600.0, "unrealized_plpc": 0.01}]
    result = build_ticker_charts((positions, None))
    btc = result["symbols"]["BTC"]
    assert btc["held"] is True
    assert btc["entry_price"] == 60000.0


# ---- build_ticker_charts: live_current_price/live_unrealized_plpc - a
# held ticker's own "up or down" verdict has to come from the live
# position, never from whichever historical bar happens to be the last
# point of the currently-selected range (that mismatch is exactly what
# made a genuinely profitable position's chart open red) ----

def test_ticker_charts_held_ticker_gets_its_live_price_and_plpc(monkeypatch):
    monkeypatch.setattr("src.alpaca_data.get_stock_bars_range", lambda symbol, interval, start, end: _bars_for_interval(interval, start, end))
    positions = [{"symbol": "AAPL", "is_crypto": False, "avg_entry_price": 305.5, "current_price": 306.0, "unrealized_plpc": 0.0016}]
    result = build_ticker_charts((positions, None))
    aapl = result["symbols"]["AAPL"]
    assert aapl["live_current_price"] == 306.0
    assert aapl["live_unrealized_plpc"] == 0.0016
    # A not-held ticker has no live position to read these from.
    qqq = result["symbols"]["QQQ"]
    assert qqq["live_current_price"] is None
    assert qqq["live_unrealized_plpc"] is None


# ---- build_ticker_charts: entry_utc - lets the frontend start the entry
# reference line exactly where the position began instead of drawing it
# across the whole visible chart ----

def test_ticker_charts_held_ticker_gets_its_real_entry_timestamp(monkeypatch):
    monkeypatch.setattr("src.alpaca_data.get_stock_bars_range", lambda symbol, interval, start, end: _bars_for_interval(interval, start, end))
    trades = _trades_df([{"ticker": "AAPL", "action": "BUY", "timestamp_utc": pd.Timestamp("2026-07-28T10:00:00+00:00")}])
    positions = [{"symbol": "AAPL", "is_crypto": False, "avg_entry_price": 305.5, "current_price": 306.0, "unrealized_plpc": 0.02}]
    result = build_ticker_charts((positions, None), trades)
    aapl = result["symbols"]["AAPL"]
    assert aapl["entry_utc"] == "2026-07-28T10:00:00+00:00"
    assert aapl["entry_is_estimated"] is False


def test_ticker_charts_held_ticker_with_no_trade_log_match_is_honestly_estimated(monkeypatch):
    monkeypatch.setattr("src.alpaca_data.get_stock_bars_range", lambda symbol, interval, start, end: _bars_for_interval(interval, start, end))
    positions = [{"symbol": "AAPL", "is_crypto": False, "avg_entry_price": 305.5, "current_price": 306.0, "unrealized_plpc": 0.02}]
    result = build_ticker_charts((positions, None), None)
    aapl = result["symbols"]["AAPL"]
    assert aapl["entry_utc"] is None
    assert aapl["entry_is_estimated"] is True
    # A not-held ticker was never "estimated" - the concept doesn't apply.
    qqq = result["symbols"]["QQQ"]
    assert qqq["entry_utc"] is None
    assert qqq["entry_is_estimated"] is False


def test_ticker_charts_crypto_entry_timestamp_matches_by_bare_ticker(monkeypatch):
    monkeypatch.setattr("src.alpaca_data.get_crypto_bars_range", lambda symbol, interval, start, end: _bars_for_interval(interval, start, end))
    trades = _trades_df([{"ticker": "BTC", "asset_class": "crypto", "action": "BUY", "timestamp_utc": pd.Timestamp("2026-07-25T09:00:00+00:00")}])
    positions = [{"symbol": "BTCUSD", "is_crypto": True, "avg_entry_price": 60000.0, "current_price": 60600.0, "unrealized_plpc": 0.01}]
    result = build_ticker_charts((positions, None), trades)
    btc = result["symbols"]["BTC"]
    assert btc["entry_utc"] == "2026-07-25T09:00:00+00:00"
    assert btc["entry_is_estimated"] is False


# ---- build_strategy_backtest_comparison: real walk-forward validation
# CSVs (results/walk_forward/) parsed and compared against the live
# account elsewhere on the site - never a live Alpaca fetch, just a
# CSV read, so tests point BACKTEST_WALK_FORWARD_FILES at temp files
# instead of hitting the real committed ones ----

def _write_csv(path, rows, columns):
    df = pd.DataFrame(rows, columns=columns)
    df.to_csv(path, index=False)


def test_backtest_comparison_computes_win_rate_only_over_traded_windows(tmp_path, monkeypatch):
    path = tmp_path / "crypto.csv"
    _write_csv(path, [
        ["BTC-USD", "2025-08-01", "2025-09-30", -0.04, 0.01, 0.05, 0.05, 2],   # win
        ["BTC-USD", "2025-09-30", "2025-11-29", -0.04, 0.01, 0.05, -0.02, 1],  # loss
        ["BTC-USD", "2025-11-29", "2026-01-28", -0.04, 0.01, 0.05, 0.0, 0],    # no signal - excluded from win rate
    ], columns=["ticker", "window_start", "window_end", "dip_threshold", "profit_target", "stop_loss", "total_return", "trades"])
    monkeypatch.setattr("site_data.BACKTEST_WALK_FORWARD_FILES", {
        "crypto": {"path": str(path), "strategy": "day_trading"},
    })
    result = build_strategy_backtest_comparison()
    crypto = result["classes"]["crypto"]
    assert crypto["available"] is True
    assert crypto["num_windows"] == 3
    assert crypto["num_traded_windows"] == 2
    assert crypto["num_profitable_windows"] == 1
    assert crypto["win_rate"] == 0.5
    assert crypto["window_start"] == "2025-08-01"
    assert crypto["window_end"] == "2026-01-28"
    assert "dip -4.0%" in crypto["config_label"]


def test_backtest_comparison_no_traded_windows_reports_none_win_rate(tmp_path, monkeypatch):
    path = tmp_path / "crypto.csv"
    _write_csv(path, [
        ["BTC-USD", "2025-08-01", "2025-09-30", -0.04, 0.01, 0.05, 0.0, 0],
    ], columns=["ticker", "window_start", "window_end", "dip_threshold", "profit_target", "stop_loss", "total_return", "trades"])
    monkeypatch.setattr("site_data.BACKTEST_WALK_FORWARD_FILES", {
        "crypto": {"path": str(path), "strategy": "day_trading"},
    })
    result = build_strategy_backtest_comparison()
    crypto = result["classes"]["crypto"]
    assert crypto["num_traded_windows"] == 0
    assert crypto["win_rate"] is None


def test_backtest_comparison_missing_csv_surfaces_reason_not_crash(tmp_path, monkeypatch):
    monkeypatch.setattr("site_data.BACKTEST_WALK_FORWARD_FILES", {
        "crypto": {"path": str(tmp_path / "does_not_exist.csv"), "strategy": "day_trading"},
    })
    result = build_strategy_backtest_comparison()
    crypto = result["classes"]["crypto"]
    assert crypto["available"] is False
    assert crypto["strategy"] == "day_trading"


def test_backtest_comparison_one_class_failure_does_not_block_the_other(tmp_path, monkeypatch):
    good_path = tmp_path / "stock.csv"
    _write_csv(good_path, [
        ["AAPL", -0.015, 0.02, "2025-08-01", "2025-09-30", 0.03, 3],
    ], columns=["ticker", "dip_threshold", "exit_threshold", "window_start", "window_end", "total_return", "trades"])
    monkeypatch.setattr("site_data.BACKTEST_WALK_FORWARD_FILES", {
        "crypto": {"path": str(tmp_path / "missing.csv"), "strategy": "day_trading"},
        "stock": {"path": str(good_path), "strategy": "rule_based"},
    })
    result = build_strategy_backtest_comparison()
    assert result["classes"]["crypto"]["available"] is False
    stock = result["classes"]["stock"]
    assert stock["available"] is True
    assert stock["win_rate"] == 1.0
    assert "dip -1.5%" in stock["config_label"]
    assert "exit 2.0%" in stock["config_label"]


# ---- build_ticker_performance: all-time per-ticker trade record (the
# same _bucket_summary rollup by_strategy/stocks_vs_crypto already use,
# just grouped by ticker) - powers each chart modal's "report card" ----

def test_ticker_performance_groups_confirmed_sells_by_ticker():
    trades = _trades_df([
        {"ticker": "AAPL", "action": "SELL", "order_status": "confirmed_fill", "price_usd": 210.0, "avg_entry_price_usd": 200.0, "position_qty_before": 10.0},
        {"ticker": "AAPL", "action": "SELL", "order_status": "confirmed_fill", "price_usd": 195.0, "avg_entry_price_usd": 200.0, "position_qty_before": 10.0},
        {"ticker": "QQQ", "action": "SELL", "order_status": "confirmed_fill", "price_usd": 520.0, "avg_entry_price_usd": 500.0, "position_qty_before": 5.0},
    ])
    trades["is_confirmed_sell"] = trades["action"] == "SELL"
    trades["realized_pnl_usd"] = (trades["price_usd"] - trades["avg_entry_price_usd"]) * trades["position_qty_before"]

    result = build_ticker_performance(trades)
    assert result["AAPL"]["num_trades"] == 2
    assert result["AAPL"]["num_wins"] == 1
    assert result["AAPL"]["win_rate"] == 0.5
    assert result["AAPL"]["realized_pnl_usd"] == 50.0  # +100 - 50
    assert result["QQQ"]["num_trades"] == 1
    assert result["QQQ"]["win_rate"] == 1.0


def test_ticker_performance_ignores_unconfirmed_and_not_placed():
    trades = _trades_df([
        {"ticker": "AAPL", "action": "SELL", "order_status": "confirmed_fill", "price_usd": 210.0, "avg_entry_price_usd": 200.0, "position_qty_before": 10.0},
        {"ticker": "AAPL", "action": "SELL", "order_status": "submitted_unconfirmed", "price_usd": 500.0, "avg_entry_price_usd": 200.0, "position_qty_before": 10.0},
        {"ticker": "AAPL", "action": "BUY", "order_status": "confirmed_fill", "price_usd": 200.0, "avg_entry_price_usd": "", "position_qty_before": 0.0},
    ])
    trades["is_confirmed_sell"] = (trades["action"] == "SELL") & (trades["order_status"] == "confirmed_fill")
    realized = pd.Series(float("nan"), index=trades.index)
    confirmed = trades["is_confirmed_sell"]
    realized[confirmed] = (
        pd.to_numeric(trades.loc[confirmed, "price_usd"])
        - pd.to_numeric(trades.loc[confirmed, "avg_entry_price_usd"], errors="coerce")
    ) * trades.loc[confirmed, "position_qty_before"]
    trades["realized_pnl_usd"] = realized

    result = build_ticker_performance(trades)
    assert result["AAPL"]["num_trades"] == 1
    assert result["AAPL"]["realized_pnl_usd"] == 100.0


def test_ticker_performance_empty_or_missing_input():
    assert build_ticker_performance(None) == {}
    assert build_ticker_performance(_trades_df([{}]).iloc[0:0]) == {}


def test_ticker_charts_report_card_reflects_all_time_trade_record(monkeypatch):
    monkeypatch.setattr("src.alpaca_data.get_stock_bars_range", lambda symbol, interval, start, end: _bars_for_interval(interval, start, end))
    trades = _trades_df([
        {"ticker": "AAPL", "action": "SELL", "order_status": "confirmed_fill", "price_usd": 210.0, "avg_entry_price_usd": 200.0, "position_qty_before": 10.0},
    ])
    trades["is_confirmed_sell"] = trades["action"] == "SELL"
    trades["realized_pnl_usd"] = (trades["price_usd"] - trades["avg_entry_price_usd"]) * trades["position_qty_before"]

    result = build_ticker_charts(([], None), trades)
    aapl_perf = result["symbols"]["AAPL"]["performance"]
    assert aapl_perf["num_trades"] == 1
    assert aapl_perf["realized_pnl_usd"] == 100.0
    # A ticker with no trades at all still gets an honest zeroed
    # report card, not a missing key the frontend would need to guard.
    qqq_perf = result["symbols"]["QQQ"]["performance"]
    assert qqq_perf["num_trades"] == 0
    assert qqq_perf["win_rate"] is None


# ---- _trade_row_json: the one shared "what does a trade row look
# like" definition trades.json (capped) and trades_full.csv (uncapped,
# the site's "Download full CSV" link) both publish from ----

def test_trade_row_json_matches_column_order():
    row = _trade_row(ticker="AAPL", action="BUY")
    row["order_status"] = classify_order_status(row)
    row["realized_pnl_usd"] = float("nan")
    result = _trade_row_json(row)
    assert list(result.keys()) == TRADE_ROW_COLUMNS


def test_trade_row_json_confirmed_sell_has_real_pnl_and_cost_basis():
    row = _trade_row(
        ticker="AAPL", action="SELL", order_placed="True", notes="",
        price_usd=210.0, avg_entry_price_usd=200.0, position_qty_before=10.0,
    )
    row["order_status"] = classify_order_status(row)
    row["realized_pnl_usd"] = (row["price_usd"] - row["avg_entry_price_usd"]) * row["position_qty_before"]
    result = _trade_row_json(row)
    assert result["price_is_confirmed_fill"] is True
    assert result["avg_entry_price_usd"] == 200.0
    assert result["realized_pnl_usd"] == 100.0


def test_trade_row_json_handles_blank_optional_fields_honestly():
    # A BUY row - no cost basis, no realized P&L, blank notional if the
    # trade was sized by quantity rather than notional dollars. None,
    # not a fabricated 0 or empty string, for every field that plainly
    # doesn't apply to this kind of row.
    row = _trade_row(action="BUY", avg_entry_price_usd="", notional_usd="")
    row["order_status"] = classify_order_status(row)
    row["realized_pnl_usd"] = float("nan")
    result = _trade_row_json(row)
    assert result["avg_entry_price_usd"] is None
    assert result["notional_usd"] is None
    assert result["realized_pnl_usd"] is None


# ---- reconcile_unconfirmed_fills: poll_for_fill (live_trade.py) only
# waits a few seconds for Alpaca to confirm a fill before giving up and
# logging "submitted_unconfirmed" - but a real order can (and, per a real
# AAPL/XOM buy that prompted this, sometimes does) go on to fill a minute
# or two later. This corrects the DISPLAYED row against Alpaca's own real
# order history, never the underlying CSV log itself. ----

UNCONFIRMED_NOTE = "Fill not confirmed within the polling window at log time - price/qty shown are decision-time estimates, not a confirmed fill."


def _reconcilable_trades_df(rows: list[dict]) -> pd.DataFrame:
    # Mirrors exactly what load_trades() itself computes (order_status/
    # is_confirmed_sell/realized_pnl_usd), since reconcile_unconfirmed_
    # fills expects to receive trades_df in that already-classified shape.
    df = _trades_df(rows)
    df["order_status"] = df.apply(classify_order_status, axis=1)
    df["is_confirmed_sell"] = (df["action"] == "SELL") & (df["order_status"] == "confirmed_fill")
    realized = pd.Series(float("nan"), index=df.index)
    confirmed = df["is_confirmed_sell"]
    if confirmed.any():
        realized[confirmed] = (
            pd.to_numeric(df.loc[confirmed, "price_usd"])
            - pd.to_numeric(df.loc[confirmed, "avg_entry_price_usd"], errors="coerce")
        ) * df.loc[confirmed, "position_qty_before"]
    df["realized_pnl_usd"] = realized
    return df


class _FakeReconcileBroker:
    """A minimal src.broker.Broker stand-in - only the one method
    reconcile_unconfirmed_fills actually calls, so a monkeypatched
    src.broker.Broker() never needs real Alpaca credentials in a test."""
    orders: list[dict] = []

    def __init__(self, allow_live: bool = True):
        pass

    def list_recent_filled_orders(self, since):
        return self.__class__.orders


def _patch_broker(monkeypatch, orders):
    fake = type("_FakeReconcileBroker", (_FakeReconcileBroker,), {"orders": orders})
    monkeypatch.setattr("src.broker.Broker", fake)


def test_reconcile_no_unconfirmed_rows_never_touches_broker(monkeypatch):
    def fail_if_called(*a, **k):
        raise AssertionError("Broker() should never be constructed when nothing is eligible")
    monkeypatch.setattr("src.broker.Broker", fail_if_called)
    now = pd.Timestamp.now(tz="UTC")
    trades = _reconcilable_trades_df([{"action": "BUY", "timestamp_utc": now, "notes": ""}])
    result = reconcile_unconfirmed_fills(trades)
    assert result.loc[0, "order_status"] == "confirmed_fill"


def test_reconcile_corrects_a_buy_that_actually_filled(monkeypatch):
    now = pd.Timestamp.now(tz="UTC")
    trades = _reconcilable_trades_df([{
        "ticker": "AAPL", "action": "BUY", "price_usd": 304.89,
        "timestamp_utc": now, "notes": UNCONFIRMED_NOTE,
    }])
    assert trades.loc[0, "order_status"] == "submitted_unconfirmed"
    _patch_broker(monkeypatch, [{
        "symbol": "AAPL", "side": "buy", "filled_qty": 6.61153719,
        "filled_avg_price": 302.65, "filled_at": now + pd.Timedelta(minutes=2),
    }])
    result = reconcile_unconfirmed_fills(trades)
    assert result.loc[0, "order_status"] == "confirmed_fill"
    assert result.loc[0, "price_usd"] == 302.65
    assert "reconciliation" in result.loc[0, "notes"].lower()


def test_reconcile_corrects_a_sell_and_recomputes_realized_pnl(monkeypatch):
    now = pd.Timestamp.now(tz="UTC")
    trades = _reconcilable_trades_df([{
        "ticker": "AAPL", "action": "SELL", "price_usd": 300.0,
        "avg_entry_price_usd": 250.0, "position_qty_before": 2.0,
        "timestamp_utc": now, "notes": UNCONFIRMED_NOTE,
    }])
    assert pd.isna(trades.loc[0, "realized_pnl_usd"])
    _patch_broker(monkeypatch, [{
        "symbol": "AAPL", "side": "sell", "filled_qty": 2.0,
        "filled_avg_price": 310.0, "filled_at": now + pd.Timedelta(seconds=45),
    }])
    result = reconcile_unconfirmed_fills(trades)
    assert result.loc[0, "is_confirmed_sell"] == True  # noqa: E712 - real numpy bool, not a mock
    assert result.loc[0, "realized_pnl_usd"] == 120.0  # (310 - 250) * 2.0


def test_reconcile_leaves_row_alone_when_no_matching_order_found(monkeypatch):
    now = pd.Timestamp.now(tz="UTC")
    trades = _reconcilable_trades_df([{
        "ticker": "AAPL", "action": "BUY", "price_usd": 304.89,
        "timestamp_utc": now, "notes": UNCONFIRMED_NOTE,
    }])
    # A real filled order exists, but for a different ticker entirely -
    # must never be mistaken for this row's own order.
    _patch_broker(monkeypatch, [{
        "symbol": "XOM", "side": "buy", "filled_qty": 13.0,
        "filled_avg_price": 153.0, "filled_at": now + pd.Timedelta(seconds=30),
    }])
    result = reconcile_unconfirmed_fills(trades)
    assert result.loc[0, "order_status"] == "submitted_unconfirmed"
    assert result.loc[0, "price_usd"] == 304.89


def test_reconcile_ignores_a_fill_outside_the_match_window(monkeypatch):
    now = pd.Timestamp.now(tz="UTC")
    trades = _reconcilable_trades_df([{
        "ticker": "AAPL", "action": "BUY", "price_usd": 304.89,
        "timestamp_utc": now, "notes": UNCONFIRMED_NOTE,
    }])
    # Same ticker/side, but filled an hour later - too far away to
    # plausibly be the same order (RECONCILE_MATCH_MINUTES is far
    # shorter), so this must not be treated as a match.
    _patch_broker(monkeypatch, [{
        "symbol": "AAPL", "side": "buy", "filled_qty": 6.6,
        "filled_avg_price": 302.65, "filled_at": now + pd.Timedelta(hours=1),
    }])
    result = reconcile_unconfirmed_fills(trades)
    assert result.loc[0, "order_status"] == "submitted_unconfirmed"


def test_reconcile_ignores_rows_older_than_the_reconcile_window(monkeypatch):
    def fail_if_called(*a, **k):
        raise AssertionError("Broker() should never be constructed for a row outside the window")
    monkeypatch.setattr("src.broker.Broker", fail_if_called)
    old = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=30)
    trades = _reconcilable_trades_df([{
        "ticker": "AAPL", "action": "BUY", "price_usd": 304.89,
        "timestamp_utc": old, "notes": UNCONFIRMED_NOTE,
    }])
    result = reconcile_unconfirmed_fills(trades)
    assert result.loc[0, "order_status"] == "submitted_unconfirmed"


def test_reconcile_broker_failure_is_non_blocking(monkeypatch):
    def raise_no_credentials(*a, **k):
        raise RuntimeError("Set ALPACA_API_KEY and ALPACA_SECRET_KEY")
    monkeypatch.setattr("src.broker.Broker", raise_no_credentials)
    now = pd.Timestamp.now(tz="UTC")
    trades = _reconcilable_trades_df([{
        "ticker": "AAPL", "action": "BUY", "price_usd": 304.89,
        "timestamp_utc": now, "notes": UNCONFIRMED_NOTE,
    }])
    result = reconcile_unconfirmed_fills(trades)
    assert result.loc[0, "order_status"] == "submitted_unconfirmed"


def test_reconcile_empty_or_missing_input():
    assert reconcile_unconfirmed_fills(None) is None
    assert reconcile_unconfirmed_fills(pd.DataFrame()).empty
