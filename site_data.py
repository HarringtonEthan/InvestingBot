"""
Generates the static JSON files the InvestingBot dashboard website (site/)
reads - the website's entire backend, in effect: no server, no database,
just plain files this script writes and a browser fetches directly.

Run by the exact same scheduled process that used to only render
results/trade_dashboard.png (see .github/workflows/update-dashboard.yml) -
this replaces that PNG with real, structured numbers a webpage can render
richly, instead of a static image. Reads the same logs/*.csv files
visualize_log.py already reads, so there's exactly one source of truth
for "what actually happened," not a second copy that could drift.

Writes eight files into --out-dir (default site/data/):
  - dashboard.json: account totals (cash/equity/buying power) plus a full
    Today/This Week/This Month/All-Time breakdown - the numbers behind
    every stat tile on the page.
  - positions.json: current open positions (crypto + stocks), only
    populated with --live-positions (same opt-in flag visualize_log.py
    already uses) - a read-only Alpaca query, never an order. Each
    position also carries its bare "ticker" (e.g. "BTC" for Alpaca's own
    "BTCUSD" symbol - see _position_ticker) so the frontend's click-to-
    chart feature can key straight into ticker_charts.json below without
    reimplementing that conversion in JS. Also carries a small "spark"
    array (~20 sampled points of the rolling 20-bar/5-minute average over
    time, see _sparkline_closes - the same average build_position_sma_
    indicators already reports as a single current reading) for the
    card's own inline sparkline - small enough to publish
    unconditionally, unlike ticker_charts.json's full range data below.
  - position_indicators.json: for each currently open rule_based/
    ml_filtered position, how far its current price sits above/below its
    own trailing 20-period SMA (pct_below_sma20) and the exit threshold
    that strategy sells at - the same "how close to selling" number
    live_trade.py's decide() already computes for day_trading but never
    for rule_based/ml_filtered (see build_position_sma_indicators).
    Skips day_trading positions - their existing unrealized gain/loss vs
    entry already serves that purpose. Only populated with
    --live-positions, same as positions.json above.
  - trades.json: recent individual trade rows (capped at
    MAX_TRADES_PUBLISHED for page weight), each carrying its own
    order_status (confirmed_fill / submitted_unconfirmed / not_placed -
    see classify_order_status() below for why those are the only three
    honest categories this project's logs can actually support). With
    --live-positions, a recent submitted_unconfirmed row also gets
    checked against Alpaca's own real order history and corrected to
    confirmed_fill if it turns out to have actually filled shortly after
    live_trade.py's own poll_for_fill() gave up waiting - see
    reconcile_unconfirmed_fills(). Also writes trades_full.csv alongside
    it - every trade ever logged, uncapped, same enriched fields, for the
    site's own "Download full CSV" link (see _trade_row_json), so real
    analysis beyond what the page itself renders doesn't require digging
    through the raw logs/*.csv files on GitHub.
  - equity.json: the raw combined equity timeline, for the equity-curve
    chart.
  - ticker_tracker.json: every ticker either live workflow watches (see
    WATCHED_STOCK_TICKERS/WATCHED_CRYPTO_TICKERS), listed alphabetically
    - not just the ones currently held - each with its last daily close,
    trailing 100-day SMA, trailing 20-period/5-minute SMA (the same
    signal rule_based/ml_filtered's own sell rule is measured against,
    computed here for every watched ticker rather than only currently-
    held ones), a small "spark" array plotting that same rolling 20-bar
    average over time for its own card sparkline (free - no second
    fetch, reuses the df already fetched for the 20-period reading right
    above it), and whether it's currently held (and if so, in profit or
    at a loss) - see build_ticker_tracker. Only populated with --live-positions,
    same as positions.json above.
  - ticker_charts.json: per-ticker price history behind every card's
    click-to-expand chart sitewide - the Ticker Tracker tab AND every
    position card on the Positions tab/charts.html both read this same
    file (keyed by the bare ticker), so any card opens the identical
    range-selectable (1 Day/1 Week/1 Month/100 Day - see
    TICKER_CHART_RANGES) chart experience no matter where it's clicked
    from. Publishes each ticker's current 100-day SMA and, for a
    currently-held ticker, its real average entry price plus the exact
    timestamp it was bought (see position_entry_timestamp) so the
    frontend can start that reference line exactly where the position
    actually began instead of drawing it across the whole visible chart,
    plus its live current price and unrealized_plpc straight from the
    position itself (never derived from this file's own historical
    bars) so the frontend's own up/down verdict always agrees with the
    number the position's own card is colored by, regardless of how
    stale the currently-selected range's last historical bar is. Also
    publishes each ticker's all-time real trade record (win rate, trade
    count, realized P&L - see build_ticker_performance) for the chart
    modal's own "report card" (see build_ticker_charts). Only populated
    with --live-positions, same as positions.json above.
  - backtest_comparison.json: real walk-forward validation results (see
    results/walk_forward/) for each asset class's exact currently-live
    config - win rate, avg return per window, and how many real windows
    that covers - the actual evidence behind README.md's own "Current
    live status" claim, published so the site can show it next to the
    account's real live-trading numbers (see build_strategy_backtest_
    comparison). Always populated - unlike every file above, this is a
    plain CSV parse of already-committed validation artifacts, needing
    neither --live-positions nor network access.

Every number here is derived from real logged/live data - nothing is
fabricated, and a missing/empty log produces an honest "no data yet"
shape in the JSON (never a guessed number), so the page can render a
graceful empty state instead of erroring or silently showing zero as if
it meant something.

Time periods (Today/This Week/This Month) are computed in US Eastern
Time (America/New_York) - see docs/AUTOMATION.md for why: that's the
stock market's own calendar, and this project already reasons about
market hours in ET everywhere else. Data is stored/compared in UTC
internally throughout; ET only enters at the boundary-computation step.
"""

# Lets type hints work without issue in this Python version.
from __future__ import annotations

# argparse for CLI flags; datetime for period-boundary math; json for
# writing the output files.
import argparse
import datetime as dt
import json
from pathlib import Path
# ZoneInfo gives real IANA timezone rules (DST transitions etc.) - needed
# for "Eastern Time" to actually mean Eastern Time year-round, not a
# fixed UTC-4/UTC-5 offset that would silently drift wrong twice a year.
from zoneinfo import ZoneInfo

import pandas as pd

# Reuses load_csv (multi-file, chronologically-sorted CSV loading) rather
# than re-implementing it - one behavior for "how do we read a log file
# that might not exist yet," not two that could quietly disagree.
from visualize_log import load_csv

ET = ZoneInfo("America/New_York")

DEFAULT_EQUITY_LOGS = ["logs/equity_log_crypto.csv", "logs/equity_log_stocks.csv"]
DEFAULT_TRADE_LOGS = ["logs/trade_log_crypto.csv", "logs/trade_log_stocks.csv"]
DEFAULT_OUT_DIR = "site/data"

# How many of the most recent trade rows to publish - the ledger doesn't
# need this project's entire trading history to be useful, and an
# ever-growing JSON file would only get slower to fetch/render for no
# real benefit.
MAX_TRADES_PUBLISHED = 200


def dedupe_trades(df: pd.DataFrame) -> pd.DataFrame:
    """
    Drops exact-duplicate rows - defensive, not expected in normal
    operation (crypto/stocks each append to their own file, and the git
    push retry loop in the trading workflows is a rebase-and-retry, not
    a mechanism that would double-append), but a manual re-run or a
    future logging change could produce one, and a duplicated SELL would
    silently double-count realized P&L and the win/loss tally otherwise.
    """
    if df is None or df.empty:
        return df
    return df.drop_duplicates().reset_index(drop=True)


def classify_order_status(row: pd.Series) -> str:
    """
    Returns one of exactly three honest categories - not a richer set
    like "canceled"/"rejected" that would look more complete but isn't
    something live_trade.py's own logging actually distinguishes today:

      - "not_placed": order_placed was False - covers a dry run (no
        --execute), a HOLD, a blocked BUY (circuit breaker, market
        closed, insufficient cash, an order already open), or a genuine
        skip. The trade log doesn't currently record *which* of those
        applied to a given HOLD-adjacent row beyond the free-text notes
        field, so this category is deliberately broad rather than
        guessing a more specific label the data doesn't actually support.
      - "submitted_unconfirmed": order_placed was True, but
        poll_for_fill() never confirmed a fill within its polling window
        (live_trade.py's own note text: "Fill not confirmed...") - the
        price/qty logged are decision-time estimates, not a confirmed
        execution.
      - "confirmed_fill": order_placed was True and a real fill was
        confirmed - price/qty are the actual, real execution.

    order_placed comes back from CSV as the literal string "True"/"False"
    (csv.DictWriter writes Python's str(bool)), not a real bool - compared
    as a string throughout, the same pattern visualize_log.py already uses.
    """
    order_placed = str(row.get("order_placed", "")) == "True"
    if not order_placed:
        return "not_placed"
    notes = str(row.get("notes", "") or "")
    if "not confirmed" in notes.lower():
        return "submitted_unconfirmed"
    return "confirmed_fill"


def load_trades(paths: list[str]) -> pd.DataFrame:
    """
    Loads and prepares the combined trade log: dedupes, classifies each
    row's order_status, and computes realized_pnl_usd for confirmed-fill
    SELLs only (see classify_order_status's docstring - an unconfirmed or
    not-placed row's price/qty aren't trustworthy enough to treat as a
    real realized gain/loss). Returns None if there's no trade data at
    all yet (a brand-new/empty log, not an error).
    """
    df = load_csv(paths)
    if df is None:
        return None
    df = dedupe_trades(df)
    df["order_status"] = df.apply(classify_order_status, axis=1)
    df["is_confirmed_sell"] = (df["action"] == "SELL") & (df["order_status"] == "confirmed_fill")
    # Only confirmed sells get a real realized_pnl_usd; everything else
    # gets NaN (not 0.0 - a real $0 gain is a fact, NaN means "not
    # applicable to this row at all," and the two must never be confused
    # in a sum/mean downstream).
    realized = pd.Series(float("nan"), index=df.index)
    confirmed = df["is_confirmed_sell"]
    if confirmed.any():
        realized[confirmed] = (
            df.loc[confirmed, "price_usd"] - df.loc[confirmed, "avg_entry_price_usd"]
        ) * df.loc[confirmed, "position_qty_before"]
    df["realized_pnl_usd"] = realized
    return df


def find_account_relaunch(equity_df: pd.DataFrame | None, trades_df: pd.DataFrame | None = None) -> tuple[pd.Timestamp, float] | None:
    """
    The most recent point the account held 100% cash - portfolio_value_usd
    == cash_usd, i.e. zero open positions - *before the account's first
    ever logged trade*, which is exactly the signature every relaunch in
    this project's history leaves behind (a fresh start with nothing
    bought yet, sometimes with a couple of earlier same-day all-cash
    blips before trading actually began for real). Returns
    (timestamp_utc, value) for the latest such row, or None if the
    equity log has no cash_usd column (older log format) or no such row
    at all.

    The "before the first trade" bound is load-bearing, not optional: a
    fully-traded account returns to 100% cash constantly and correctly
    as a normal, expected part of trading (every position closing out at
    once, even briefly) - completely unrelated to a relaunch. Without
    this bound, the very next such moment - which *will* happen again -
    gets misread as "the account was just relaunched," collapsing All
    Time/This Week/This Month down to that instant and making weeks of
    real trade history vanish from every period's stats while the
    underlying CSV logs stay completely intact (real incident:
    2026-08-14, the first time the account closed its last position
    since the 2026-07-28 relaunch). trades_df is optional only so
    callers that already know there are no trades at all yet (a
    brand-new account) don't need to construct an empty DataFrame just
    to call this.

    This is the honest, code-verifiable answer to "when did the account's
    current run actually begin" - not a hand-typed date, and not inferred
    indirectly from trade-log file archiving. It's used as a floor under
    every period's own calendar boundary: a calendar cutoff (midnight ET,
    the 1st of the month, ...) that falls before the account's most
    recent relaunch would otherwise pull in now-irrelevant pre-relaunch
    history (an earlier bug-fix reset, a paused-and-relaunched account)
    into "this week" / "this month" / "all time," which is never what
    those labels should mean for a live paper account.
    """
    if equity_df is None or equity_df.empty or "cash_usd" not in equity_df.columns:
        return None
    candidates = equity_df
    if trades_df is not None and not trades_df.empty:
        first_trade_ts = pd.Timestamp(trades_df["timestamp_utc"].min())
        candidates = equity_df[equity_df["timestamp_utc"] <= first_trade_ts]
        if candidates.empty:
            return None
    full_cash = candidates[(candidates["cash_usd"] - candidates["portfolio_value_usd"]).abs() < 0.01]
    if full_cash.empty:
        return None
    row = full_cash.iloc[-1]
    return pd.Timestamp(row["timestamp_utc"]), float(row["portfolio_value_usd"])


def period_bounds(
    now_utc: dt.datetime, relaunch_utc: dt.datetime | None = None
) -> dict[str, tuple[dt.datetime, dt.datetime]]:
    """
    Returns {period_name: (start_utc, end_utc)} for "today", "week", and
    "month" - each period runs from its Eastern-Time calendar boundary
    (midnight ET for today/month, Monday midnight ET for week) through
    "right now". "all_time" isn't included here - it has no fixed start
    at all (see summarize_period()'s caller), so it doesn't fit this
    tuple-of-bounds shape.

    Computed by converting `now_utc` into ET first, finding that
    period's ET calendar boundary, then converting *that* boundary back
    to UTC - so a DST transition (which shifts the UTC offset, not the
    ET wall-clock time) is handled correctly by construction, not by a
    fixed-offset approximation that would drift wrong twice a year.

    `relaunch_utc`, when given (see find_account_relaunch above), floors
    every boundary at the account's own most recent relaunch: a calendar
    boundary earlier than that point is bumped forward to it, so "this
    week"/"this month" never quietly starts counting from before the
    account's current run began. Once enough real calendar time has
    passed that a boundary naturally falls after the relaunch, the floor
    stops doing anything and normal calendar semantics take back over -
    no special-casing needed for that transition.
    """
    now_et = now_utc.astimezone(ET)
    today_start_et = now_et.replace(hour=0, minute=0, second=0, microsecond=0)
    # Monday is weekday() == 0 - subtract however many days since Monday
    # to land on this week's own Monday, at midnight ET.
    week_start_et = today_start_et - dt.timedelta(days=today_start_et.weekday())
    month_start_et = today_start_et.replace(day=1)
    bounds_utc = {
        "today": today_start_et.astimezone(dt.timezone.utc),
        "week": week_start_et.astimezone(dt.timezone.utc),
        "month": month_start_et.astimezone(dt.timezone.utc),
    }
    if relaunch_utc is not None:
        bounds_utc = {k: max(v, relaunch_utc) for k, v in bounds_utc.items()}
    return {k: (v, now_utc) for k, v in bounds_utc.items()}


def _equity_value_asof(equity_df: pd.DataFrame | None, ts: dt.datetime) -> float | None:
    """
    The last known portfolio_value_usd at or before `ts`, or None if
    nothing was logged yet by that point. This is what a period's
    "starting value" actually means: equity_log.csv only gets a new row
    when the value *changes* (see live_trade.py's log_equity dedup), so
    the true value at the start of "today" is very likely a row logged
    yesterday (or earlier), not a row timestamped exactly at midnight -
    carrying the last known value forward is the correct way to read
    that log, not an approximation of it.
    """
    if equity_df is None or equity_df.empty:
        return None
    ts = pd.Timestamp(ts)
    prior = equity_df[equity_df["timestamp_utc"] <= ts]
    if prior.empty:
        return None
    return float(prior.iloc[-1]["portfolio_value_usd"])


def _max_drawdown(values: list[float]) -> float | None:
    """
    Largest peak-to-trough fractional decline within `values`, as a
    negative fraction (e.g. -0.05 = a 5% drawdown) - same convention
    src/backtest.py's run_backtest() uses. None if fewer than 2 points
    exist (a single point has no "trough" to measure against a "peak").
    """
    if len(values) < 2:
        return None
    peak = values[0]
    worst = 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, (v - peak) / peak)
    return worst


def summarize_period(
    label: str,
    start_utc: dt.datetime | None,
    end_utc: dt.datetime,
    equity_df: pd.DataFrame | None,
    trades_df: pd.DataFrame | None,
    unrealized_total: float | None,
    unrealized_by_class: dict[str, float] | None,
) -> dict:
    """
    Builds one period's full summary dict (see module docstring for the
    field list) - called once each for today/week/month/all_time with
    the appropriate window, so all four periods are guaranteed to share
    identical logic and can never quietly diverge from each other.

    start_utc=None means "all time" - no fixed starting boundary, so the
    starting value is simply the first row ever logged (equivalent to
    "no hardcoded baseline," which replaces the old visualize_log.py
    --baseline flag's fixed dollar amount entirely - see CHANGELOG.md).
    """
    result = {
        "label": label,
        "start_utc": start_utc.isoformat() if start_utc is not None else None,
        "end_utc": end_utc.isoformat(),
        "starting_value_usd": None,
        "starting_value_asof_utc": None,
        "ending_value_usd": None,
        "dollar_pnl_usd": None,
        "pct_return": None,
        "realized_pnl_usd": 0.0,
        "unrealized_pnl_usd": unrealized_total,
        "unrealized_pnl_by_asset_class": unrealized_by_class or {},
        "num_trades": 0,
        "num_wins": 0,
        "num_losses": 0,
        "win_rate": None,
        "best_trade": None,
        "worst_trade": None,
        "stocks_vs_crypto": {},
        "by_strategy": {},
        "max_drawdown": None,
        "has_equity_data": False,
        "starting_value_is_first_available": False,
        "trade_log_reset_during_period": False,
    }

    # ---- Equity-based figures: starting/ending value, $ P&L, % return, drawdown ----
    if equity_df is not None and not equity_df.empty:
        window = equity_df
        if start_utc is not None:
            window = equity_df[
                (equity_df["timestamp_utc"] >= pd.Timestamp(start_utc))
                & (equity_df["timestamp_utc"] <= pd.Timestamp(end_utc))
            ]
        starting = None
        starting_ts = None
        if start_utc is None:
            # "all time" - no fixed start, so the true starting point is
            # simply the first row ever logged (this is what replaces the
            # old hardcoded --baseline dollar amount entirely).
            starting = float(equity_df.iloc[0]["portfolio_value_usd"])
            starting_ts = equity_df.iloc[0]["timestamp_utc"]
        else:
            prior = equity_df[equity_df["timestamp_utc"] <= pd.Timestamp(start_utc)]
            if not prior.empty:
                starting = float(prior.iloc[-1]["portfolio_value_usd"])
                starting_ts = prior.iloc[-1]["timestamp_utc"]
            elif not window.empty:
                # Nothing was logged before this period's own calendar
                # start (e.g. the account was reset partway through
                # today, so there's no "value at midnight ET" to carry
                # forward) - fall back to the first value actually
                # logged *within* the period instead of reporting no
                # data at all, same principle "all time" already uses.
                # Flagged explicitly so this isn't mistaken for a true
                # start-of-period balance.
                starting = float(window.iloc[0]["portfolio_value_usd"])
                starting_ts = window.iloc[0]["timestamp_utc"]
                result["starting_value_is_first_available"] = True

        # Reset/relaunch anchor: trade_log_*.csv gets archived and
        # restarted fresh on a same-day relaunch, but equity_log_*.csv
        # never resets - so `starting` above can still be carried forward
        # from *before* a relaunch that happened inside this period. When
        # the earliest trade currently on record is newer than that
        # carried-forward point, some trade history was archived away,
        # and the honest baseline for what this account is currently
        # doing is the last known equity right before that earliest
        # trade - always the full-cash point a relaunch leaves right
        # before its first buy. This isn't a hardcoded dollar figure:
        # it's read straight off the equity log the same way every other
        # baseline here is, so it stays correct on its own after future
        # relaunches too instead of needing a number typed in by hand.
        if trades_df is not None and not trades_df.empty and starting_ts is not None:
            earliest_trade_ts = pd.Timestamp(trades_df["timestamp_utc"].min())
            if earliest_trade_ts > pd.Timestamp(starting_ts):
                reset_prior = equity_df[equity_df["timestamp_utc"] <= earliest_trade_ts]
                if not reset_prior.empty:
                    reset_row = reset_prior.iloc[-1]
                    if pd.Timestamp(reset_row["timestamp_utc"]) > pd.Timestamp(starting_ts):
                        starting = float(reset_row["portfolio_value_usd"])
                        starting_ts = reset_row["timestamp_utc"]
                        result["starting_value_is_first_available"] = False
                        result["trade_log_reset_during_period"] = True

        # Prefer the freshest value at/before `end_utc` (handles a
        # live-appended "right now" point, or a period whose end isn't
        # literally the very last row in the whole file).
        ending = _equity_value_asof(equity_df, end_utc)
        if starting is not None and ending is not None:
            result["starting_value_usd"] = round(starting, 2)
            # Exposed so update-dashboard.yml can hand this exact same
            # dynamically-computed anchor to visualize_log.py's
            # --baseline/--baseline-since - without it, the PNG dashboard
            # would fall back to its own default (the first row of the
            # equity log), reintroducing the stale-pre-reset-baseline bug
            # this field's computation above just fixed for the website.
            result["starting_value_asof_utc"] = pd.Timestamp(starting_ts).isoformat() if starting_ts is not None else None
            result["ending_value_usd"] = round(ending, 2)
            result["dollar_pnl_usd"] = round(ending - starting, 2)
            result["pct_return"] = (ending / starting - 1.0) if starting else None
            result["has_equity_data"] = True
            # Drawdown measured across the window's own points, prefixed
            # with the starting value itself so a decline right at the
            # start of the period is still visible as a drawdown from it.
            series = [starting] + window["portfolio_value_usd"].tolist()
            result["max_drawdown"] = _max_drawdown(series)

    # ---- Trade-based figures: realized P&L, win/loss, best/worst, splits ----
    if trades_df is not None and not trades_df.empty:
        window = trades_df
        if start_utc is not None:
            window = trades_df[
                (trades_df["timestamp_utc"] >= pd.Timestamp(start_utc))
                & (trades_df["timestamp_utc"] <= pd.Timestamp(end_utc))
            ]
        confirmed_sells = window[window["is_confirmed_sell"]]
        result["realized_pnl_usd"] = round(float(confirmed_sells["realized_pnl_usd"].sum()), 2) if len(confirmed_sells) else 0.0
        # "Number of trades" here means completed round trips (a
        # confirmed BUY-then-SELL cycle) - a submitted-but-unconfirmed or
        # not-placed order didn't actually change the account, so it
        # isn't a "trade" in the sense win/loss/win-rate care about. See
        # README.md's dashboard section for this exact definition and
        # where the raw attempt counts (buys, unconfirmed, not-placed)
        # are still surfaced separately, nothing is hidden.
        result["num_trades"] = int(len(confirmed_sells))
        wins = confirmed_sells[confirmed_sells["realized_pnl_usd"] > 0]
        losses = confirmed_sells[confirmed_sells["realized_pnl_usd"] <= 0]
        result["num_wins"] = int(len(wins))
        result["num_losses"] = int(len(losses))
        if result["num_trades"] > 0:
            result["win_rate"] = result["num_wins"] / result["num_trades"]
        # Only consider sells with a computable P&L - a confirmed sell
        # whose avg_entry_price_usd came back blank (a real logging gap:
        # e.g. live_trade.py once only fetched the cost basis for the
        # day_trading strategy, so a rule_based/ml_filtered sell could
        # log an empty one) has a NaN realized_pnl_usd, and idxmax/idxmin
        # raise ValueError on an all-NaN column rather than just skipping
        # it - exactly what crashed this script's scheduled run. Still
        # counted in num_trades above (it's a real completed round trip),
        # just excluded here since there's nothing to rank it by.
        #
        # best_trade/worst_trade are populated independently, each only
        # from the side of the ledger that actually supports the label:
        # "Best Trade" only ever names a real winner, "Worst Trade" only
        # ever names a real loser (or breakeven). Without this split, a
        # day with exactly one trade - a loss - would show that same
        # loss as both the "best" and "worst" trade, which reads as if
        # something good happened when nothing did.
        known_pnl = confirmed_sells[confirmed_sells["realized_pnl_usd"].notna()]
        winners = known_pnl[known_pnl["realized_pnl_usd"] > 0]
        losers = known_pnl[known_pnl["realized_pnl_usd"] <= 0]
        if len(winners):
            result["best_trade"] = _trade_summary(winners.loc[winners["realized_pnl_usd"].idxmax()])
        if len(losers):
            result["worst_trade"] = _trade_summary(losers.loc[losers["realized_pnl_usd"].idxmin()])

        result["num_buys"] = int((window["action"] == "BUY").sum())
        result["num_unconfirmed"] = int((window["order_status"] == "submitted_unconfirmed").sum())
        result["num_not_placed"] = int((window["order_status"] == "not_placed").sum())

        for asset_class in ("crypto", "stock"):
            subset = confirmed_sells[confirmed_sells["asset_class"] == asset_class]
            result["stocks_vs_crypto"][asset_class] = _bucket_summary(subset)

        if "strategy" in confirmed_sells.columns:
            for strategy in sorted(confirmed_sells["strategy"].dropna().unique()):
                subset = confirmed_sells[confirmed_sells["strategy"] == strategy]
                result["by_strategy"][strategy] = _bucket_summary(subset)

    return result


# Column order for _trade_row_json's dict below, and for trades_full.csv's
# header when there are zero rows to derive it from - one literal list
# instead of two that could silently drift apart.
TRADE_ROW_COLUMNS = [
    "timestamp_utc", "mode", "asset_class", "ticker", "strategy", "action", "price_usd",
    "price_is_confirmed_fill", "notional_usd", "position_qty_before", "avg_entry_price_usd",
    "realized_pnl_usd", "order_status", "notes",
]


def _trade_row_json(row: pd.Series) -> dict:
    """
    One trade log row as the enriched dict both trades.json (capped to
    MAX_TRADES_PUBLISHED) and the full trades_full.csv export (every
    row ever logged) publish - one definition of "what a trade row
    looks like on this site" instead of two that could quietly drift
    apart. Same fields the Trade History table and its detail modal
    already read. Keys match TRADE_ROW_COLUMNS's order above.
    """
    return {
        "timestamp_utc": row["timestamp_utc"].isoformat(),
        "mode": row["mode"],
        "asset_class": row["asset_class"],
        "ticker": row["ticker"],
        "strategy": row["strategy"],
        "action": row["action"],
        "price_usd": float(row["price_usd"]),
        "price_is_confirmed_fill": row["order_status"] == "confirmed_fill",
        "notional_usd": float(row["notional_usd"]) if pd.notna(row["notional_usd"]) and row["notional_usd"] != "" else None,
        "position_qty_before": float(row["position_qty_before"]) if pd.notna(row["position_qty_before"]) else None,
        "avg_entry_price_usd": float(row["avg_entry_price_usd"]) if pd.notna(row["avg_entry_price_usd"]) and row["avg_entry_price_usd"] != "" else None,
        "realized_pnl_usd": round(float(row["realized_pnl_usd"]), 2) if pd.notna(row["realized_pnl_usd"]) else None,
        "order_status": row["order_status"],
        "notes": row["notes"] if pd.notna(row.get("notes")) else "",
    }


def _trade_summary(row: pd.Series) -> dict:
    return {
        "timestamp_utc": row["timestamp_utc"].isoformat(),
        "ticker": row["ticker"],
        "asset_class": row["asset_class"],
        "strategy": row["strategy"],
        "realized_pnl_usd": round(float(row["realized_pnl_usd"]), 2),
    }


def _bucket_summary(sells: pd.DataFrame) -> dict:
    """Shared realized-P&L/win-rate rollup for one bucket of confirmed
    sells (one asset class, or one strategy) - same shape either way."""
    n = len(sells)
    wins = int((sells["realized_pnl_usd"] > 0).sum()) if n else 0
    return {
        "num_trades": int(n),
        "realized_pnl_usd": round(float(sells["realized_pnl_usd"].sum()), 2) if n else 0.0,
        "num_wins": wins,
        "win_rate": (wins / n) if n else None,
    }


def build_ticker_performance(trades_df: pd.DataFrame | None) -> dict[str, dict]:
    """
    All-time real trade performance per ticker - the exact same
    confirmed-fill-sell/win-rate/realized-P&L definition summarize_
    period's own by_strategy/stocks_vs_crypto buckets already use (see
    _bucket_summary above), just grouped by ticker instead of by
    strategy or period. Powers each ticker's chart-modal "report card"
    (see build_ticker_charts) - deliberately all-time and independent
    of whatever Today/Week/Month/All Time period happens to be selected
    elsewhere on the page, since "how has this ticker done for this bot,
    ever" is a different question than "this period's numbers."

    trades_df's own "ticker" column is already the bare form
    (WATCHED_STOCK_TICKERS/WATCHED_CRYPTO_TICKERS' own form, e.g. "BTC")
    live_trade.py logs directly - no Alpaca-symbol conversion needed
    here, unlike the live-position-matching helpers elsewhere in this
    file that start from Alpaca's own symbol instead.
    """
    if trades_df is None or trades_df.empty or "is_confirmed_sell" not in trades_df.columns:
        return {}
    confirmed_sells = trades_df[trades_df["is_confirmed_sell"]]
    return {
        ticker: _bucket_summary(confirmed_sells[confirmed_sells["ticker"] == ticker])
        for ticker in sorted(confirmed_sells["ticker"].dropna().unique())
    }


def _last_open_buy_row(trades_df: pd.DataFrame | None, ticker: str) -> pd.Series | None:
    """
    The most recent BUY logged for this ticker, as long as no SELL has
    been logged for it since (a SELL after that BUY would mean the
    position shown live isn't the one that BUY opened - e.g. it was
    closed and manually re-bought outside the bot). Returns None if the
    trade log doesn't clearly support one - shared by
    attribute_position_strategy (which strategy opened this position) and
    position_entry_timestamp (when it was opened), so the two can never
    disagree about which BUY row a given open position traces back to.
    """
    if trades_df is None or trades_df.empty:
        return None
    ticker_rows = trades_df[trades_df["ticker"] == ticker].sort_values("timestamp_utc")
    if ticker_rows.empty:
        return None
    last_buy = ticker_rows[ticker_rows["action"] == "BUY"]
    if last_buy.empty:
        return None
    last_buy_row = last_buy.iloc[-1]
    later_sell = ticker_rows[(ticker_rows["action"] == "SELL") & (ticker_rows["timestamp_utc"] > last_buy_row["timestamp_utc"])]
    if not later_sell.empty:
        return None
    return last_buy_row


def attribute_position_strategy(trades_df: pd.DataFrame | None, ticker: str) -> str | None:
    """
    Best-effort guess at which strategy currently holds a given open
    position (see _last_open_buy_row for the exact rule). Alpaca's own
    position data has no concept of "strategy" at all (that's purely this
    project's own bookkeeping), so None ("unknown") is the honest answer
    whenever the trade log doesn't clearly support a better one - never
    guessed from the ticker alone.
    """
    row = _last_open_buy_row(trades_df, ticker)
    return row["strategy"] if row is not None else None


def position_entry_timestamp(trades_df: pd.DataFrame | None, ticker: str) -> pd.Timestamp | None:
    """
    When the currently-open position in `ticker` was opened, by the exact
    same rule attribute_position_strategy uses - so a position card's
    "since purchase" chart start date can never disagree with the
    strategy label shown right next to it. None means the trade log
    doesn't clearly support a single answer (e.g. multiple buy/sell
    cycles with no unambiguous last opening), not that the position has
    no history at all - callers should fall back to a fixed recent
    lookback window rather than guess.
    """
    row = _last_open_buy_row(trades_df, ticker)
    return pd.Timestamp(row["timestamp_utc"]) if row is not None else None


def build_positions_payload(live_positions_result: tuple[list[dict], str | None] | None, trades_df: pd.DataFrame | None) -> dict:
    """
    live_positions_result is (positions, error) from fetch_live_positions()
    below, or None if --live-positions was never passed at all - a
    third, distinct state from "fetched successfully but zero open
    positions," so the page can tell "we didn't check" apart from
    "we checked: nothing's open."
    """
    if live_positions_result is None:
        return {"available": False, "reason": "live position lookup not requested for this run", "positions": []}
    positions, error = live_positions_result
    if error is not None:
        return {"available": False, "reason": error, "positions": []}

    from src.alpaca_data import get_crypto_bars_range, get_stock_bars_range
    from src.features import add_features
    from src.symbols import resolve_symbol

    now_utc = dt.datetime.now(dt.timezone.utc)
    # Same interval/lookback as the "vs 20-bar avg" indicator itself (see
    # SMA_INDICATOR_BAR_INTERVAL/SMA_INDICATOR_LOOKBACK_DAYS below) - the
    # card sparkline plots that exact rolling average over time, not raw
    # price, so it needs to be computed from the same bars that single
    # current-value stat already reads.
    start_date = (now_utc - dt.timedelta(days=SMA_INDICATOR_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    end_date = (now_utc + dt.timedelta(days=1)).strftime("%Y-%m-%d")

    enriched = []
    for p in positions:
        # The trade log's own "ticker" column always uses the bare form
        # live_trade.py's --ticker CLI arg does (e.g. "BTC") - Alpaca's
        # positions endpoint returns crypto symbols without a slash
        # instead (e.g. "BTCUSD"), which never matches that column as-is.
        # Converting first is what lets a crypto position's strategy
        # actually be found instead of always coming back "unknown".
        # `ticker` is also published here so the frontend can key its
        # own click-to-chart lookup (ticker_charts.json) by the same
        # bare form build_ticker_charts already uses, instead of
        # reimplementing this conversion in JS.
        ticker = _position_ticker(p["symbol"], p["is_crypto"])
        # Card sparkline: a small number of open positions at any given
        # time makes a dedicated short fetch per position cheap - unlike
        # ticker_charts.json's full range data, this is small enough to
        # publish unconditionally rather than gating behind a click. One
        # ticker's fetch failing (delisted, rate-limited, etc.) never
        # blocks any other position's card or its own other fields.
        try:
            if p["is_crypto"]:
                spark_df = get_crypto_bars_range(resolve_symbol(ticker).alpaca, SMA_INDICATOR_BAR_INTERVAL, start_date, end_date)
            else:
                spark_df = get_stock_bars_range(ticker, SMA_INDICATOR_BAR_INTERVAL, start_date, end_date)
            spark = _sparkline_closes(add_features(spark_df)["sma20"])
        except Exception:
            spark = []
        enriched.append({**p, "ticker": ticker, "strategy": attribute_position_strategy(trades_df, ticker), "spark": spark})
    return {"available": True, "reason": None, "positions": enriched}


# How many points a card sparkline (positions.json/ticker_tracker.json's
# "spark" field) samples down to - just enough to show real recent shape
# at a glance, small enough that publishing one per watched ticker never
# meaningfully grows page weight (unlike ticker_charts.json's full
# range data, which is why that file stays fetched on-demand instead).
SPARK_MAX_POINTS = 20


def _sparkline_closes(values: pd.Series | None, max_points: int = SPARK_MAX_POINTS) -> list[float]:
    """
    Same even-stride-plus-keep-the-last-bar downsampling as _thin_points,
    but returns bare numbers (no timestamps) - a card sparkline only ever
    draws relative shape, never exact times, so publishing timestamps
    here would just be wasted bytes repeated for every watched ticker.
    Takes whatever per-bar series a caller wants plotted (build_positions_
    payload/build_ticker_tracker both feed it a 20-period rolling average
    - see SMA_INDICATOR_BAR_INTERVAL below - not raw price, since that
    average is the exact same signal already shown as this card's own
    "vs 20-bar avg" text stat).
    """
    if values is None or values.empty:
        return []
    values = values.dropna()
    n = len(values)
    if n < 2:
        return []
    if n > max_points:
        step = max(1, n // max_points)
        keep_idx = sorted(set(range(0, n, step)) | {n - 1})
        values = values.iloc[keep_idx]
    return [round(float(v), 6) for v in values]


# Cap on published points per symbol/range - keeps ticker_charts.json
# small regardless of how fine-grained a given range's bar interval is.
MAX_POINTS_PER_SYMBOL = 300


def _thin_points(df: pd.DataFrame, max_points: int = MAX_POINTS_PER_SYMBOL) -> list[dict]:
    """
    Downsamples a Close-price DataFrame to at most `max_points` rows for
    publishing, always keeping the very first and very last real bar
    (the two points a "since purchase" chart most needs to be honest
    about: what it was actually worth at entry, and what it's actually
    worth right now) rather than an even stride that could drop either.
    """
    if df is None or df.empty:
        return []
    n = len(df)
    if n > max_points:
        step = max(1, n // max_points)
        keep_idx = sorted(set(range(0, n, step)) | {n - 1})
        df = df.iloc[keep_idx]
    return [
        {"t": pd.Timestamp(ts).isoformat(), "price": round(float(row["Close"]), 6)}
        for ts, row in df.iterrows()
    ]


# The live stock workflow's --exit-threshold (see
# .github/workflows/paper-trade-stocks.yml) - rule_based/ml_filtered sell
# when price recovers to this far *above* its own 20-period SMA. Not
# read from the workflow file itself (that would need a YAML-parsing
# dependency this project doesn't otherwise have just for a display
# label); if that flag's value ever changes, this constant needs a
# matching manual update, same as dip_threshold/profit_target elsewhere
# in this file already require.
RULE_BASED_EXIT_THRESHOLD = 0.02

# Buy-side dip thresholds - the same pct_below_sma20 reading, but the
# level a *not-yet-held* ticker's entry decision is measured against
# (see paper-trade-stocks.yml/paper-trade-crypto.yml's own
# --dip-threshold). Stocks and crypto use different values; crypto's
# day_trading strategy also exits on profit-target/stop-loss against its
# own entry price rather than this SMA recovering, so unlike
# RULE_BASED_EXIT_THRESHOLD there is no crypto equivalent of that one -
# a held crypto position's own unrealized P&L already covers "how close
# to selling" for that case. Same manual-sync caveat as
# RULE_BASED_EXIT_THRESHOLD above.
RULE_BASED_DIP_THRESHOLD = -0.015
DAY_TRADING_DIP_THRESHOLD = -0.04

# Bar interval and lookback window used only to compute the *current*
# pct_below_sma20 reading below - deliberately short and always ending
# "now," unlike build_position_price_histories's since-entry fetch.
# A position opened minutes ago still needs 20 bars of *trailing*
# history before it, which its own short lifetime could never supply -
# this window exists independent of when the position was opened.
SMA_INDICATOR_BAR_INTERVAL = "5m"
SMA_INDICATOR_LOOKBACK_DAYS = 10


def build_position_sma_indicators(
    live_positions_result: tuple[list[dict], str | None] | None,
    trades_df: pd.DataFrame | None,
) -> dict:
    """
    For each currently open rule_based/ml_filtered position, computes the
    exact number that strategy's own sell rule is measured against:
    pct_below_sma20, how far the current price sits above/below its own
    trailing 20-period simple moving average (see src/features.py's
    add_features - same formula, bit-for-bit). live_trade.py's decide()
    only ever computes this for the day_trading branch, never for
    rule_based/ml_filtered, so today the live logs never show a "how
    close to selling" number for a held rule_based position - this
    reproduces that missing number for the dashboard instead of the logs.

    Deliberately skips day_trading positions: that strategy's sell rule
    is instead measured against gain-vs-entry-price, which is exactly
    the unrealized gain/loss the position card already displays - a
    second number here would be redundant, not additive.

    Same best-effort-per-symbol contract as build_ticker_tracker: one
    ticker's fetch failing (or not having 20 bars of trailing history
    yet) never blocks another symbol's reading or the rest of this run.
    """
    if live_positions_result is None:
        return {"available": False, "reason": "live position lookup not requested for this run", "symbols": {}}
    positions, error = live_positions_result
    if error is not None:
        return {"available": False, "reason": error, "symbols": {}}
    if not positions:
        return {"available": True, "reason": None, "symbols": {}}

    from src.alpaca_data import get_crypto_bars_range, get_stock_bars_range
    from src.features import add_features
    from src.symbols import resolve_symbol

    now_utc = dt.datetime.now(dt.timezone.utc)
    start_date = (now_utc - dt.timedelta(days=SMA_INDICATOR_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    end_date = (now_utc + dt.timedelta(days=1)).strftime("%Y-%m-%d")
    symbols_payload: dict[str, dict] = {}

    for p in positions:
        symbol = p["symbol"]
        # trades_df's own "ticker" column is always the bare form (e.g.
        # "BTC") - Alpaca's position symbol needs the same conversion
        # build_ticker_tracker/build_positions_payload already use before
        # this can ever match a crypto position's logged rows.
        ticker = _position_ticker(symbol, p["is_crypto"])
        strategy = attribute_position_strategy(trades_df, ticker)
        if strategy not in ("rule_based", "ml_filtered"):
            continue

        try:
            if p["is_crypto"]:
                df = get_crypto_bars_range(resolve_symbol(ticker).alpaca, SMA_INDICATOR_BAR_INTERVAL, start_date, end_date)
            else:
                df = get_stock_bars_range(symbol, SMA_INDICATOR_BAR_INTERVAL, start_date, end_date)
            pct_series = add_features(df)["pct_below_sma20"].dropna()
            if pct_series.empty:
                symbols_payload[symbol] = {
                    "available": False,
                    "reason": "not enough trailing bars yet to compute a 20-period average",
                    "pct_vs_sma20": None,
                    "exit_threshold": RULE_BASED_EXIT_THRESHOLD,
                }
            else:
                symbols_payload[symbol] = {
                    "available": True,
                    "reason": None,
                    "pct_vs_sma20": round(float(pct_series.iloc[-1]), 6),
                    "exit_threshold": RULE_BASED_EXIT_THRESHOLD,
                }
        except Exception as e:
            # Same non-blocking reasoning as build_position_price_histories:
            # one symbol's bars being unfetchable is never a reason to
            # drop every other position's reading.
            symbols_payload[symbol] = {
                "available": False,
                "reason": f"{type(e).__name__}: {e}",
                "pct_vs_sma20": None,
                "exit_threshold": RULE_BASED_EXIT_THRESHOLD,
            }

    return {"available": True, "reason": None, "symbols": symbols_payload}


# The full universe of tickers each live workflow currently watches -
# kept in sync by hand with .github/workflows/paper-trade-stocks.yml and
# paper-trade-crypto.yml's own --ticker lists (same manual-sync tradeoff
# as RULE_BASED_EXIT_THRESHOLD above: whoever changes a workflow's
# --ticker list needs to update this too). Order here is preserved as
# published, matching the order each workflow already watches them in.
WATCHED_STOCK_TICKERS = ["SPY", "AAPL", "QQQ", "JPM", "XOM", "JNJ", "KO", "CAT", "DIS"]
WATCHED_CRYPTO_TICKERS = ["BTC", "ETH", "SOL", "DOGE", "LTC", "AVAX", "LINK", "XRP", "DOT"]

# A classic, widely-recognized trend window - deliberately longer than
# RULE_BASED_EXIT_THRESHOLD's 20-bar/5-minute window above, which is
# specific to that one strategy's own sell rule. This is a general "how
# is this ticker doing lately" reading for the whole watched universe,
# not tied to any particular strategy's decision - daily bars, not
# intraday, since a 100-bar trend is normally read as ~100 trading days,
# not 100 five-minute ticks.
TICKER_TRACKER_SMA_PERIODS = 100
# Calendar days of daily bars to request - comfortably more than 100
# *trading* days once weekends/holidays are accounted for (stocks only;
# crypto trades every day so needs far less, but requesting the same
# window for both keeps this simple and the extra crypto history is cheap).
TICKER_TRACKER_LOOKBACK_DAYS = 220


def _position_ticker(symbol: str, is_crypto: bool) -> str:
    """
    The bare ticker string live_trade.py actually logs (its own --ticker
    CLI arg verbatim, e.g. "BTC") and that WATCHED_STOCK_TICKERS/
    WATCHED_CRYPTO_TICKERS above use - needed to match a live position
    (keyed by Alpaca's own positions-endpoint symbol, e.g. "BTCUSD" for
    crypto, no slash - see broker.py's get_all_positions) back against
    one of those watched tickers. Stock symbols already match as-is;
    crypto's slash-less "BTCUSD" needs its quote currency stripped first.
    """
    if not is_crypto:
        return symbol
    if symbol.endswith("USD") and len(symbol) > 3:
        return symbol[:-3]
    return symbol


def build_ticker_tracker(live_positions_result: tuple[list[dict], str | None] | None) -> dict:
    """
    Every ticker either live workflow watches - not just the ones
    currently held - each with its last daily close, its trailing
    100-day SMA, and how far apart those two are, so it's visible at a
    glance whether a *watched* ticker is trending above or below its own
    longer-run average, independent of whether the bot happens to be
    holding it right now. A held ticker also gets its live unrealized
    P&L sign attached (see position_state below), the same information
    the Positions tab's card outline already conveys - this reuses that
    same "held right now" signal rather than recomputing whether a
    position is open by some second method.

    current_price/sma100/pct_vs_sma100 all come from the same daily-bar
    series for a given ticker (never mixed with a position's own live,
    intraday current_price) - comparing a stale end-of-day average
    against a live intraday quote would be internally inconsistent, and
    "last close" is honestly labeled as such rather than implied to be
    "right now".

    Same opt-in/best-effort contract as build_position_price_histories
    and build_position_sma_indicators: unavailable (not just unfetched)
    when --live-positions wasn't passed or failed, and one ticker's own
    bars fetch failing never blocks any other ticker's row.
    """
    if live_positions_result is None:
        return {"available": False, "reason": "live position lookup not requested for this run", "categories": {"stocks": [], "crypto": []}}
    positions, error = live_positions_result
    if error is not None:
        return {"available": False, "reason": error, "categories": {"stocks": [], "crypto": []}}

    from src.alpaca_data import get_crypto_bars_range, get_stock_bars_range
    from src.features import add_features
    from src.symbols import resolve_symbol

    held_by_ticker = {_position_ticker(p["symbol"], p["is_crypto"]): p for p in positions}

    now_utc = dt.datetime.now(dt.timezone.utc)
    start_date = (now_utc - dt.timedelta(days=TICKER_TRACKER_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    start_date_20 = (now_utc - dt.timedelta(days=SMA_INDICATOR_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    end_date = (now_utc + dt.timedelta(days=1)).strftime("%Y-%m-%d")

    def build_row(ticker: str, is_crypto: bool) -> dict:
        held_position = held_by_ticker.get(ticker)
        held = held_position is not None
        unrealized_plpc = held_position["unrealized_plpc"] if held else None
        if not held:
            position_state = "not_held"
        elif unrealized_plpc > 0:
            position_state = "profit"
        elif unrealized_plpc < 0:
            position_state = "loss"
        else:
            position_state = "flat"

        row = {
            "ticker": ticker,
            "is_crypto": is_crypto,
            "held": held,
            "position_state": position_state,
            "unrealized_plpc": unrealized_plpc,
            # Static workflow constants, not fetched - always present so the
            # card can label pct_vs_sma20 below with "buys at"/"sells at"
            # context regardless of whether that fetch itself succeeds.
            "dip_threshold": DAY_TRADING_DIP_THRESHOLD if is_crypto else RULE_BASED_DIP_THRESHOLD,
            "exit_threshold": None if is_crypto else RULE_BASED_EXIT_THRESHOLD,
        }
        try:
            if is_crypto:
                df = get_crypto_bars_range(resolve_symbol(ticker).alpaca, "1d", start_date, end_date)
            else:
                df = get_stock_bars_range(ticker, "1d", start_date, end_date)
            sma_series = df["Close"].rolling(TICKER_TRACKER_SMA_PERIODS).mean().dropna()
            current_price = float(df["Close"].iloc[-1])
            if sma_series.empty:
                row.update(available=False, reason="not enough trailing daily bars yet to compute a 100-day average",
                            last_close=current_price, sma100=None, pct_vs_sma100=None)
            else:
                sma100 = float(sma_series.iloc[-1])
                row.update(available=True, reason=None,
                            last_close=current_price, sma100=sma100, pct_vs_sma100=(current_price - sma100) / sma100)
        except Exception as e:
            # Same non-blocking reasoning as build_position_price_histories:
            # one ticker's bars being unfetchable never blocks the rest.
            row.update(available=False, reason=f"{type(e).__name__}: {e}", last_close=None, sma100=None, pct_vs_sma100=None)

        # Independent second fetch/metric: the same 20-period/5-minute
        # SMA rule_based/ml_filtered's own sell rule is measured against
        # (see build_position_sma_indicators), but computed here for
        # *every* watched ticker rather than only currently-held
        # rule_based/ml_filtered positions - a separate available/reason
        # pair so this metric failing (or the 100-day one above failing)
        # never hides the other.
        try:
            if is_crypto:
                df20 = get_crypto_bars_range(resolve_symbol(ticker).alpaca, SMA_INDICATOR_BAR_INTERVAL, start_date_20, end_date)
            else:
                df20 = get_stock_bars_range(ticker, SMA_INDICATOR_BAR_INTERVAL, start_date_20, end_date)
            featured = add_features(df20)
            pct20_series = featured["pct_below_sma20"].dropna()
            # Card sparkline: this same rolling 20-bar average over time,
            # not raw price - the exact signal pct_vs_sma20 below is a
            # single current reading of, so the line and the number next
            # to it on the card always tell the same story. Free (no
            # second fetch) since featured is already in memory; empty
            # rather than a guess if there aren't yet 20 bars to average.
            row["spark"] = _sparkline_closes(featured["sma20"])
            if pct20_series.empty:
                row.update(sma20_available=False, sma20_reason="not enough trailing bars yet to compute a 20-period average",
                            sma20=None, pct_vs_sma20=None)
            else:
                row.update(sma20_available=True, sma20_reason=None,
                            sma20=float(featured["sma20"].dropna().iloc[-1]), pct_vs_sma20=round(float(pct20_series.iloc[-1]), 6))
        except Exception as e:
            row.update(sma20_available=False, sma20_reason=f"{type(e).__name__}: {e}", sma20=None, pct_vs_sma20=None, spark=[])

        return row

    return {
        "available": True,
        "reason": None,
        "as_of_utc": now_utc.isoformat(),
        "categories": {
            # Alphabetical, not the workflow's own watch-list order - a
            # ticker tracker is for quickly finding one specific ticker,
            # unlike WATCHED_STOCK_TICKERS/WATCHED_CRYPTO_TICKERS itself,
            # which stays in the workflow's order for easy diffing
            # against paper-trade-stocks.yml/paper-trade-crypto.yml.
            "stocks": [build_row(t, False) for t in sorted(WATCHED_STOCK_TICKERS)],
            "crypto": [build_row(t, True) for t in sorted(WATCHED_CRYPTO_TICKERS)],
        },
    }


# The four ranges the Ticker Tracker's click-to-expand chart lets you
# switch between - each gets its own fixed bar interval (what "1 Day"
# actually means is 5-minute bars, not a zoomed-in slice of daily ones)
# and its own fetch buffer (generous enough to cover a weekend/holiday
# gap before slicing down to the real display window below).
# window_days is the real display window for every range except "100d",
# which instead keeps exactly the last TICKER_TRACKER_SMA_PERIODS daily
# bars - the same 100 bars its own SMA is computed from, not a separate
# 100-*calendar*-day slice that could disagree with it.
TICKER_CHART_RANGES = {
    "1d": {"interval": "5m", "fetch_lookback_days": 5, "window_days": 1},
    "1w": {"interval": "15m", "fetch_lookback_days": 10, "window_days": 7},
    "1m": {"interval": "1h", "fetch_lookback_days": 45, "window_days": 30},
    "100d": {"interval": "1d", "fetch_lookback_days": TICKER_TRACKER_LOOKBACK_DAYS, "window_days": None},
}


def build_ticker_charts(
    live_positions_result: tuple[list[dict], str | None] | None,
    trades_df: pd.DataFrame | None = None,
) -> dict:
    """
    Per-ticker price history behind every card's click-to-expand chart
    sitewide - not just the Ticker Tracker tab. Position cards on the
    Positions tab and charts.html read this exact same file (keyed by
    the bare ticker), so any card anywhere on the site opens the
    identical range-selectable chart, at each of the four
    TICKER_CHART_RANGES above - covers every ticker build_ticker_tracker
    does (not just held positions), so any watched ticker can be
    inspected regardless of whether the bot happens to be holding it
    right now.

    Also publishes each ticker's current 100-day SMA (computed from the
    exact same 100 daily bars as the "100d" range's own points, not a
    second, potentially-drifting calculation) so the chart can draw it
    as a reference line - the same number build_ticker_tracker already
    shows as text on the card. A currently-held ticker additionally gets
    its real average entry price (straight from the live position, not
    re-derived from the trade log, so it can never disagree with the
    position card's own P&L) plus the exact timestamp that position was
    opened (see position_entry_timestamp) - entry_utc lets the frontend
    draw that reference line starting only from where the position
    actually began, instead of implying it was held for the entire
    visible range. entry_is_estimated is True when the trade log can't
    clearly support a single entry (see position_entry_timestamp) - the
    frontend falls back to drawing the line across the whole chart in
    that case rather than guessing a start point. A held ticker also
    gets live_current_price/live_unrealized_plpc, straight from the
    position object rather than derived from any of this function's own
    historical bars - the frontend needs a live number to color its own
    up/down verdict by, since comparing entry_price against whichever
    historical bar happens to be the range's own last point (e.g.
    yesterday's close on the default 100-day view) can disagree with
    the live figure the position's card is itself colored by.

    Also publishes each ticker's all-time real trade record (see
    build_ticker_performance) - num_trades/win_rate/realized_pnl_usd
    from every confirmed-fill sell ever logged for that exact ticker,
    independent of whether it's currently held or which period happens
    to be selected elsewhere on the page. Powers the chart modal's own
    "report card," shown right below the chart itself.

    Best-effort per range, not just per ticker: one range failing for a
    ticker (e.g. Alpaca has no 5-minute bars for a thinly-traded name)
    never blocks that ticker's other ranges or any other ticker.

    Same opt-in contract as build_ticker_tracker: unavailable (not just
    unfetched) when --live-positions wasn't passed or failed - this
    function doesn't itself need live position data for its bars, but
    does need it for held/entry_price above, and sharing one opt-in gate
    across every Alpaca-backed JSON file is simpler than a second flag.
    """
    if live_positions_result is None:
        return {"available": False, "reason": "live position lookup not requested for this run", "symbols": {}}
    positions, error = live_positions_result
    if error is not None:
        return {"available": False, "reason": error, "symbols": {}}

    from src.alpaca_data import get_crypto_bars_range, get_stock_bars_range
    from src.symbols import resolve_symbol

    held_by_ticker = {_position_ticker(p["symbol"], p["is_crypto"]): p for p in positions}
    ticker_performance = build_ticker_performance(trades_df)
    empty_performance = {"num_trades": 0, "realized_pnl_usd": 0.0, "num_wins": 0, "win_rate": None}

    now_utc = dt.datetime.now(dt.timezone.utc)
    end_date = (now_utc + dt.timedelta(days=1)).strftime("%Y-%m-%d")

    def build_symbol(ticker: str, is_crypto: bool) -> dict:
        held_position = held_by_ticker.get(ticker)
        held = held_position is not None
        entry_price = held_position["avg_entry_price"] if held else None
        # Straight from the live position, same as entry_price above -
        # NOT derived from any of this function's own historical bars.
        # The frontend needs this so a held ticker's chart always agrees
        # with its own card: comparing entry_price against whichever
        # historical bar happens to be the last point in the currently-
        # selected range (e.g. yesterday's daily close on the default
        # 100-day view) can disagree with the live number the card
        # itself is colored by, purely because price moved since that
        # bar closed - not because anything is actually wrong.
        live_current_price = held_position["current_price"] if held else None
        live_unrealized_plpc = held_position["unrealized_plpc"] if held else None
        # trades_df's own "ticker" column is already the bare form (this
        # `ticker` param comes straight from WATCHED_STOCK_TICKERS/
        # WATCHED_CRYPTO_TICKERS, never from Alpaca's own symbol) so no
        # conversion is needed here, unlike build_positions_payload/
        # build_position_sma_indicators which start from a live position's
        # Alpaca symbol instead.
        entry_ts = position_entry_timestamp(trades_df, ticker) if held else None
        entry_is_estimated = held and entry_ts is None
        ranges_payload: dict[str, dict] = {}
        sma100 = None
        for range_key, cfg in TICKER_CHART_RANGES.items():
            try:
                start_date = (now_utc - dt.timedelta(days=cfg["fetch_lookback_days"])).strftime("%Y-%m-%d")
                if is_crypto:
                    df = get_crypto_bars_range(resolve_symbol(ticker).alpaca, cfg["interval"], start_date, end_date)
                else:
                    df = get_stock_bars_range(ticker, cfg["interval"], start_date, end_date)
                if cfg["window_days"] is None:
                    sma_series = df["Close"].rolling(TICKER_TRACKER_SMA_PERIODS).mean().dropna()
                    if not sma_series.empty:
                        sma100 = float(sma_series.iloc[-1])
                    df = df.tail(TICKER_TRACKER_SMA_PERIODS)
                else:
                    window_start = now_utc - dt.timedelta(days=cfg["window_days"])
                    df = df[df.index >= window_start]
                ranges_payload[range_key] = {"available": True, "reason": None, "interval": cfg["interval"], "points": _thin_points(df)}
            except Exception as e:
                # Same non-blocking reasoning as build_ticker_tracker: one
                # range's bars being unfetchable never blocks the rest.
                ranges_payload[range_key] = {"available": False, "reason": f"{type(e).__name__}: {e}", "interval": None, "points": []}
        available = any(r["available"] for r in ranges_payload.values())
        return {
            "available": available,
            "reason": None if available else "none of this ticker's chart ranges could be fetched",
            "sma100": sma100,
            "held": held,
            "entry_price": entry_price,
            "entry_utc": entry_ts.isoformat() if entry_ts is not None else None,
            "entry_is_estimated": entry_is_estimated,
            "live_current_price": live_current_price,
            "live_unrealized_plpc": live_unrealized_plpc,
            "performance": ticker_performance.get(ticker, empty_performance),
            "ranges": ranges_payload,
        }

    symbols_payload: dict[str, dict] = {}
    for ticker in WATCHED_STOCK_TICKERS:
        symbols_payload[ticker] = build_symbol(ticker, False)
    for ticker in WATCHED_CRYPTO_TICKERS:
        symbols_payload[ticker] = build_symbol(ticker, True)

    return {"available": True, "reason": None, "symbols": symbols_payload}


# Which committed walk-forward validation CSV backs each asset class's
# exact currently-live config - see results/walk_forward/README.md,
# which documents this same mapping in prose ("Which files back the
# ACTIVE live config"). If either live config ever changes, whoever
# changes it needs to update this too (same manual-sync tradeoff as
# RULE_BASED_EXIT_THRESHOLD/WATCHED_STOCK_TICKERS above), and re-run
# walk_forward.py to regenerate the CSV itself.
BACKTEST_WALK_FORWARD_FILES = {
    "crypto": {"path": "results/walk_forward/walk_forward.csv", "strategy": "day_trading"},
    "stock": {"path": "results/walk_forward/walk_forward_stocks_5m_best.csv", "strategy": "rule_based"},
}


def build_strategy_backtest_comparison() -> dict:
    """
    Real walk-forward validation results for each asset class's exact
    currently-live config (see BACKTEST_WALK_FORWARD_FILES above) - the
    actual evidence behind this project's own "Current live status"
    claim in README.md, published here so the website can show it next
    to the account's own real live-trading numbers (dashboard.json's
    periods[period].stocks_vs_crypto already has those) instead of only
    in a static markdown file. Never runs a fresh backtest itself -
    these CSVs are already-committed validation artifacts written by
    walk_forward.py, not live-refetched - so reading them is just a
    parse: no Alpaca credentials or network access needed, and this is
    always available regardless of whether --live-positions was passed.

    Only counts a window toward the win rate if the strategy actually
    traded in it (trades > 0) - a window with zero trades means "no
    signal fired that window," not "the strategy lost," and folding it
    into a literal win/loss tally would understate how often the
    strategy is actually right on the windows it does act in.

    Best-effort per asset class: one class's CSV being missing or
    malformed (e.g. before a first walk_forward.py run) never blocks
    the other's real numbers from showing.
    """
    classes: dict[str, dict] = {}
    for asset_class, cfg in BACKTEST_WALK_FORWARD_FILES.items():
        try:
            df = pd.read_csv(cfg["path"])
            if df.empty:
                raise ValueError("walk-forward CSV has no rows")
            traded = df[df["trades"] > 0]
            num_traded_windows = int(len(traded))
            num_profitable_windows = int((traded["total_return"] > 0).sum()) if num_traded_windows else 0
            win_rate = (num_profitable_windows / num_traded_windows) if num_traded_windows else None

            # A human-readable config label built entirely from the
            # CSV's own columns (never a hardcoded number living a
            # second place it could quietly drift from) - whichever of
            # these threshold columns this particular file actually has.
            config_bits = []
            for col, label in (("dip_threshold", "dip"), ("profit_target", "profit"), ("exit_threshold", "exit"), ("stop_loss", "stop")):
                if col in df.columns:
                    config_bits.append(f"{label} {float(df[col].iloc[0]) * 100:.1f}%")

            classes[asset_class] = {
                "available": True,
                "reason": None,
                "strategy": cfg["strategy"],
                "config_label": ", ".join(config_bits),
                "num_windows": int(len(df)),
                "num_traded_windows": num_traded_windows,
                "num_profitable_windows": num_profitable_windows,
                "win_rate": win_rate,
                "avg_return_per_window": round(float(df["total_return"].mean()), 6),
                "num_tickers": int(df["ticker"].nunique()) if "ticker" in df.columns else None,
                "window_start": str(df["window_start"].min()) if "window_start" in df.columns else None,
                "window_end": str(df["window_end"].max()) if "window_end" in df.columns else None,
            }
        except Exception as e:
            # Same non-blocking reasoning as every other Alpaca-backed
            # builder in this file: one class's own data being
            # unreadable never blocks the other's.
            classes[asset_class] = {"available": False, "reason": f"{type(e).__name__}: {e}", "strategy": cfg["strategy"]}

    return {"available": True, "reason": None, "classes": classes}


def fetch_live_positions():
    """
    Returns (positions, error, cash, equity, buying_power) - error is
    None on success, in which case cash/equity/buying_power are all real
    numbers; on any failure, positions is [] and cash/equity/buying_power
    are all None (never partially populated). Imported/called lazily
    from main() only when --live-positions is passed, same reasoning as
    visualize_log.py's own --live-positions: running this script at all
    should never require alpaca-py or ALPACA_* credentials unless this
    specific opt-in feature is actually being used. Never raises -
    any failure (missing credentials, network error, Alpaca API error)
    comes back as a clear reason string instead of crashing the whole
    generation run over an optional enhancement.
    """
    try:
        from src.broker import Broker

        broker = Broker(allow_live=True)  # read-only query - never places an order
        cash = broker.get_cash()
        equity = broker.get_equity()
        buying_power = broker.get_buying_power()
        positions = broker.get_all_positions()
        return positions, None, cash, equity, buying_power
    except Exception as e:
        return [], f"{type(e).__name__}: {e}", None, None, None


# How far back a submitted_unconfirmed row is still worth reconciling -
# older than this, not worth another Alpaca query; if it hasn't filled by
# then it likely never will (a stock BUY is a DAY order and expires at
# market close if genuinely never filled).
RECONCILE_WINDOW_DAYS = 3
# How close a real filled order's own fill timestamp has to be to a trade
# log row's own logged timestamp to count as "the same order" - generous
# enough to cover Alpaca's occasionally-slow notional/fractional fills
# (observed in practice: a real buy that filled about two minutes after
# being logged), tight enough that two genuinely different orders for the
# same ticker/side essentially never both fall inside it - already
# structurally unlikely since has_open_order() (live_trade.py) stops a
# second BUY from ever stacking on an unfilled one for the same ticker.
RECONCILE_MATCH_MINUTES = 20


def reconcile_unconfirmed_fills(trades_df: pd.DataFrame | None) -> pd.DataFrame | None:
    """
    live_trade.py's poll_for_fill() only waits a few seconds for Alpaca to
    confirm a just-submitted order before giving up and logging it as
    "submitted_unconfirmed" - honest at the time, but Alpaca's own paper-
    trading engine can take noticeably longer to actually fill a notional/
    fractional order (real example that prompted this: an AAPL buy that
    filled about two minutes after being logged, and an XOM buy that
    filled within about a minute - both genuinely executed, just slower
    than the poll window). Without this, a trade that DID fill stays
    mislabeled "unconfirmed" - and its price shown as a stale decision-
    time estimate - forever, which reads as something went wrong when
    nothing did.

    This corrects the DISPLAYED data only - trade_log_*.csv itself is
    never rewritten, so it stays exactly what live_trade.py actually
    observed at decision time. Same "enrich with live context, never
    rewrite history" pattern positions.json/ticker_tracker.json's own
    --live-positions data already uses.

    Best-effort and non-blocking, same as every other --live-positions
    feature in this file: any failure (missing credentials, network
    error, nothing eligible to check) leaves trades_df exactly as
    load_trades() returned it.
    """
    if trades_df is None or trades_df.empty or "order_status" not in trades_df.columns:
        return trades_df
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=RECONCILE_WINDOW_DAYS)
    eligible_mask = (trades_df["order_status"] == "submitted_unconfirmed") & (trades_df["timestamp_utc"] >= cutoff)
    if not eligible_mask.any():
        return trades_df

    try:
        from src.broker import Broker
        from src.symbols import resolve_symbol

        broker = Broker(allow_live=True)  # read-only query - never places an order
        since = (trades_df.loc[eligible_mask, "timestamp_utc"].min() - pd.Timedelta(minutes=RECONCILE_MATCH_MINUTES)).to_pydatetime()
        filled_orders = broker.list_recent_filled_orders(since)
    except Exception:
        return trades_df
    if not filled_orders:
        return trades_df

    tolerance = pd.Timedelta(minutes=RECONCILE_MATCH_MINUTES)
    for idx, row in trades_df.loc[eligible_mask].iterrows():
        try:
            alpaca_symbol = resolve_symbol(row["ticker"]).alpaca
        except Exception:
            continue
        side = str(row["action"]).lower()
        row_ts = row["timestamp_utc"]
        best, best_gap = None, None
        for order in filled_orders:
            if order["symbol"] != alpaca_symbol or order["side"] != side or order["filled_at"] is None:
                continue
            gap = abs(pd.Timestamp(order["filled_at"]) - row_ts)
            if gap > tolerance:
                continue
            if best_gap is None or gap < best_gap:
                best, best_gap = order, gap
        if best is None or best["filled_avg_price"] is None:
            continue
        trades_df.at[idx, "price_usd"] = best["filled_avg_price"]
        trades_df.at[idx, "order_status"] = "confirmed_fill"
        trades_df.at[idx, "notes"] = (
            f"Confirmed after the fact via reconciliation - Alpaca's own order "
            f"history shows this filled at ${best['filled_avg_price']:.6f}, about "
            f"{int(best_gap.total_seconds())}s after being logged as unconfirmed "
            f"(poll_for_fill's window had already elapsed)."
        )

    # Re-derive is_confirmed_sell/realized_pnl_usd from the (possibly
    # just-corrected) order_status column - same computation load_trades()
    # itself already does. A newly-confirmed SELL should count toward
    # realized P&L exactly like one that confirmed within the poll window.
    trades_df["is_confirmed_sell"] = (trades_df["action"] == "SELL") & (trades_df["order_status"] == "confirmed_fill")
    realized = pd.Series(float("nan"), index=trades_df.index)
    confirmed = trades_df["is_confirmed_sell"]
    if confirmed.any():
        realized[confirmed] = (
            pd.to_numeric(trades_df.loc[confirmed, "price_usd"])
            - pd.to_numeric(trades_df.loc[confirmed, "avg_entry_price_usd"], errors="coerce")
        ) * trades_df.loc[confirmed, "position_qty_before"]
    trades_df["realized_pnl_usd"] = realized
    return trades_df


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--equity-log", nargs="+", default=DEFAULT_EQUITY_LOGS)
    parser.add_argument("--trade-log", nargs="+", default=DEFAULT_TRADE_LOGS)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--live-positions", action="store_true",
                         help="pull current positions/cash/equity/buying-power from Alpaca "
                              "(needs ALPACA_API_KEY/ALPACA_SECRET_KEY) - read-only, never places an order")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    equity_df = load_csv(args.equity_log)
    trades_df = load_trades(args.trade_log)

    now_utc = dt.datetime.now(dt.timezone.utc)

    cash = equity = buying_power = None
    unrealized_total = None
    unrealized_by_class: dict[str, float] = {}
    live_result = None
    if args.live_positions:
        # Needs the same live Alpaca access --live-positions already
        # opts into, so it only runs here - see reconcile_unconfirmed_
        # fills's own docstring for why this never touches the CSV logs
        # themselves, only this in-memory copy every downstream JSON/CSV
        # output below is built from.
        trades_df = reconcile_unconfirmed_fills(trades_df)
        positions, error, cash, equity, buying_power = fetch_live_positions()
        live_result = (positions, error)
        if error is None:
            unrealized_total = round(sum(p["unrealized_pl"] for p in positions), 2)
            unrealized_by_class = {
                "crypto": round(sum(p["unrealized_pl"] for p in positions if p["is_crypto"]), 2),
                "stock": round(sum(p["unrealized_pl"] for p in positions if not p["is_crypto"]), 2),
            }
            # Same reasoning as visualize_log.py's append_live_equity_point:
            # a live-pulled "right now" equity value keeps every period's
            # "ending_value_usd" describing this exact instant, not
            # whatever the last 5-minute trading cron happened to log.
            live_row = pd.DataFrame([{"timestamp_utc": pd.Timestamp(now_utc), "portfolio_value_usd": equity}])
            equity_df = pd.concat([equity_df, live_row], ignore_index=True).sort_values("timestamp_utc") if equity_df is not None else live_row

    relaunch = find_account_relaunch(equity_df, trades_df)
    relaunch_ts, relaunch_value = relaunch if relaunch is not None else (None, None)

    bounds = period_bounds(now_utc, relaunch_ts)
    all_time_start = relaunch_ts if relaunch_ts is not None else None
    periods = {
        "today": summarize_period("Today", bounds["today"][0], bounds["today"][1], equity_df, trades_df, unrealized_total, unrealized_by_class),
        "week": summarize_period("This Week", bounds["week"][0], bounds["week"][1], equity_df, trades_df, unrealized_total, unrealized_by_class),
        "month": summarize_period("This Month", bounds["month"][0], bounds["month"][1], equity_df, trades_df, unrealized_total, unrealized_by_class),
        "all_time": summarize_period("All Time", all_time_start, now_utc, equity_df, trades_df, unrealized_total, unrealized_by_class),
    }

    dashboard = {
        "generated_at_utc": now_utc.isoformat(),
        "generated_at_et": now_utc.astimezone(ET).isoformat(),
        "timezone_note": "today/week/month boundaries are US Eastern Time (America/New_York); all timestamps in the data files themselves are UTC",
        "account": {
            "cash_usd": round(cash, 2) if cash is not None else None,
            "equity_usd": round(equity, 2) if equity is not None else None,
            "buying_power_usd": round(buying_power, 2) if buying_power is not None else None,
            "available": args.live_positions and live_result is not None and live_result[1] is None,
        },
        "account_relaunch": {
            "detected": relaunch_ts is not None,
            "timestamp_utc": relaunch_ts.isoformat() if relaunch_ts is not None else None,
            "timestamp_et": relaunch_ts.astimezone(ET).isoformat() if relaunch_ts is not None else None,
            "value_usd": round(relaunch_value, 2) if relaunch_value is not None else None,
        },
        "periods": periods,
        "methodology": {
            "baseline": "each period's starting value is the last known account equity at or before that period's own start (carried forward from whenever it was last logged, not a fixed dollar amount) - all_time starts from the very first row ever logged, with no hardcoded baseline",
            "relaunch_floor": "every period's calendar start is floored at the account's most recent full-cash relaunch point (the last logged moment portfolio_value_usd == cash_usd, i.e. zero open positions) - a calendar boundary earlier than that is bumped forward to it, so pre-relaunch history never bleeds into today/this week/this month/all time; see account_relaunch above for the exact point detected",
            "num_trades": "counts only confirmed-fill SELL executions (completed round trips); submitted-but-unconfirmed and not-placed orders are tracked separately (see num_buys/num_unconfirmed/num_not_placed) and never counted as a trade",
            "realized_pnl": "computed only from confirmed fills; a submitted-but-unconfirmed order's price is a decision-time estimate, not treated as realized",
        },
    }

    (out_dir / "dashboard.json").write_text(json.dumps(dashboard, indent=2))

    positions_payload = build_positions_payload(live_result, trades_df)
    (out_dir / "positions.json").write_text(json.dumps(positions_payload, indent=2))

    position_indicators_payload = build_position_sma_indicators(live_result, trades_df)
    (out_dir / "position_indicators.json").write_text(json.dumps(position_indicators_payload, indent=2))

    ticker_tracker_payload = build_ticker_tracker(live_result)
    (out_dir / "ticker_tracker.json").write_text(json.dumps(ticker_tracker_payload, indent=2))

    ticker_charts_payload = build_ticker_charts(live_result, trades_df)
    (out_dir / "ticker_charts.json").write_text(json.dumps(ticker_charts_payload, indent=2))

    backtest_comparison_payload = build_strategy_backtest_comparison()
    (out_dir / "backtest_comparison.json").write_text(json.dumps(backtest_comparison_payload, indent=2))

    if trades_df is not None and not trades_df.empty:
        all_trades_sorted = trades_df.sort_values("timestamp_utc", ascending=False)
        recent = all_trades_sorted.head(MAX_TRADES_PUBLISHED)
        trades_payload = {
            "available": True,
            "trades": [_trade_row_json(row) for _, row in recent.iterrows()],
        }
        # The page itself only ever shows MAX_TRADES_PUBLISHED rows (page-
        # weight reasons - see that constant's own comment), but anyone
        # who wants to do their own analysis (pivot tables, longer-term
        # trends) shouldn't have to go dig the raw CSVs out of the repo to
        # get the rest. This is every row ever logged, oldest first (the
        # natural order for a spreadsheet), with the exact same enriched
        # fields (computed order_status, realized_pnl_usd) trades.json
        # itself publishes - genuinely more useful for analysis than the
        # raw logs/*.csv files, which don't have those derived columns.
        full_csv_rows = [_trade_row_json(row) for _, row in all_trades_sorted.sort_values("timestamp_utc").iterrows()]
        pd.DataFrame(full_csv_rows).to_csv(out_dir / "trades_full.csv", index=False)
    else:
        trades_payload = {"available": False, "trades": []}
        # An honest empty CSV (header row only) rather than no file at
        # all - the download link always has something valid to point to.
        pd.DataFrame(columns=TRADE_ROW_COLUMNS).to_csv(out_dir / "trades_full.csv", index=False)
    (out_dir / "trades.json").write_text(json.dumps(trades_payload, indent=2))

    if equity_df is not None and not equity_df.empty:
        equity_payload = {
            "available": True,
            "points": [
                {"timestamp_utc": row["timestamp_utc"].isoformat(), "portfolio_value_usd": float(row["portfolio_value_usd"])}
                for _, row in equity_df.iterrows()
            ],
        }
    else:
        equity_payload = {"available": False, "points": []}
    (out_dir / "equity.json").write_text(json.dumps(equity_payload, indent=2))

    print(f"Wrote dashboard/positions/position_indicators/trades/equity/ticker_tracker/ticker_charts/backtest_comparison JSON to {out_dir}/")


if __name__ == "__main__":
    main()
