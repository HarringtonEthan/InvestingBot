"""
Generates the static JSON files the casino dashboard website (site/) reads -
the website's entire backend, in effect: no server, no database, just
plain files this script writes and a browser fetches directly.

Run by the exact same scheduled process that used to only render
results/trade_dashboard.png (see .github/workflows/update-dashboard.yml) -
this replaces that PNG with real, structured numbers a webpage can render
richly, instead of a static image. Reads the same logs/*.csv files
visualize_log.py already reads, so there's exactly one source of truth
for "what actually happened," not a second copy that could drift.

Writes six files into --out-dir (default site/data/):
  - dashboard.json: account totals (cash/equity/buying power) plus a full
    Today/This Week/This Month/All-Time breakdown - the numbers behind
    every slot-machine reel and stat tile on the page.
  - positions.json: current open positions (crypto + stocks), only
    populated with --live-positions (same opt-in flag visualize_log.py
    already uses) - a read-only Alpaca query, never an order.
  - position_history.json: real historical closing prices per currently
    open position, from that position's own entry date (see
    position_entry_timestamp) through now - only populated with
    --live-positions, same as positions.json above. Powers each position
    card's "price since purchase" chart on the website.
  - position_indicators.json: for each currently open rule_based/
    ml_filtered position, how far its current price sits above/below its
    own trailing 20-period SMA (pct_below_sma20) and the exit threshold
    that strategy sells at - the same "how close to selling" number
    live_trade.py's decide() already computes for day_trading but never
    for rule_based/ml_filtered (see build_position_sma_indicators).
    Skips day_trading positions - their existing unrealized gain/loss vs
    entry already serves that purpose. Only populated with
    --live-positions, same as positions.json above.
  - trades.json: recent individual trade rows, each carrying its own
    order_status (confirmed_fill / submitted_unconfirmed / not_placed -
    see classify_order_status() below for why those are the only three
    honest categories this project's logs can actually support).
  - equity.json: the raw combined equity timeline, for the equity-curve
    chart.

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


def find_account_relaunch(equity_df: pd.DataFrame | None) -> tuple[pd.Timestamp, float] | None:
    """
    The most recent point the account held 100% cash - portfolio_value_usd
    == cash_usd, i.e. zero open positions - which is exactly the signature
    every relaunch in this project's history leaves behind (a fresh start
    with nothing bought yet). Returns (timestamp_utc, value) for the
    latest such row, or None if the equity log has no cash_usd column
    (older log format) or no such row at all.

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
    full_cash = equity_df[(equity_df["cash_usd"] - equity_df["portfolio_value_usd"]).abs() < 0.01]
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
    enriched = []
    for p in positions:
        enriched.append({**p, "strategy": attribute_position_strategy(trades_df, p["symbol"])})
    return {"available": True, "reason": None, "positions": enriched}


# How far back to look when a position's entry date can't be determined
# from the trade log (see position_entry_timestamp) - a reasonable
# "recent history" window rather than refusing to show a chart at all.
FALLBACK_LOOKBACK_DAYS = 90
# Cap on published points per symbol - keeps position_history.json small
# regardless of how fine-grained the chosen bar interval is.
MAX_POINTS_PER_SYMBOL = 300


def _pick_bar_interval(span: dt.timedelta) -> str:
    """
    Coarser bars for a longer span, so a position held for months doesn't
    request tens of thousands of 1-minute bars just to end up thinned
    back down anyway - matches the interval strings src/alpaca_data.py's
    _INTERVAL_MAP already understands.
    """
    days = span.total_seconds() / 86400
    if days <= 1:
        return "5m"
    if days <= 7:
        return "15m"
    if days <= 30:
        return "1h"
    if days <= 120:
        return "4h"
    return "1d"


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


def _crypto_alpaca_symbol(symbol: str) -> str:
    """
    Alpaca's positions endpoint returns crypto symbols without the "/"
    (e.g. "BTCUSD" - see broker.py's get_all_positions), but its bars
    endpoint needs the slash form ("BTC/USD"). Every pair this project
    trades quotes in USD (see src/symbols.py), so reinserting the slash
    before a trailing "USD" round-trips correctly without needing a
    hardcoded list of bases.
    """
    if "/" in symbol:
        return symbol
    if symbol.endswith("USD") and len(symbol) > 3:
        return f"{symbol[:-3]}/USD"
    return symbol


def build_position_price_histories(
    live_positions_result: tuple[list[dict], str | None] | None,
    trades_df: pd.DataFrame | None,
) -> dict:
    """
    For each currently open position, fetches real historical closing
    prices from Alpaca from the position's entry date (see
    position_entry_timestamp) through now - the data behind the "price
    since purchase" chart on a position card. Best-effort per symbol: a
    fetch failure for one ticker (rate limit, an unsupported/new symbol,
    a network blip) is recorded as that symbol's own "unavailable" state
    and never blocks the rest of this function or the rest of site_data's
    output. Same opt-in reasoning as fetch_live_positions: only reachable
    when --live-positions was passed, and only imports alpaca-py then.
    """
    if live_positions_result is None:
        return {"available": False, "reason": "live position lookup not requested for this run", "symbols": {}}
    positions, error = live_positions_result
    if error is not None:
        return {"available": False, "reason": error, "symbols": {}}
    if not positions:
        return {"available": True, "reason": None, "symbols": {}}

    from src.alpaca_data import get_crypto_bars_range, get_stock_bars_range

    now_utc = dt.datetime.now(dt.timezone.utc)
    end_date = (now_utc + dt.timedelta(days=1)).strftime("%Y-%m-%d")
    symbols_payload: dict[str, dict] = {}

    for p in positions:
        symbol = p["symbol"]
        is_crypto = p["is_crypto"]
        entry_ts = position_entry_timestamp(trades_df, symbol)
        entry_is_estimated = entry_ts is None
        start_dt = entry_ts.to_pydatetime() if entry_ts is not None else (now_utc - dt.timedelta(days=FALLBACK_LOOKBACK_DAYS))
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=dt.timezone.utc)
        # A position opened moments ago would otherwise request an
        # empty/invalid (start == end) range.
        if (now_utc - start_dt) < dt.timedelta(hours=1):
            start_dt = now_utc - dt.timedelta(hours=1)
        interval = _pick_bar_interval(now_utc - start_dt)
        start_date = start_dt.strftime("%Y-%m-%d")

        try:
            if is_crypto:
                df = get_crypto_bars_range(_crypto_alpaca_symbol(symbol), interval, start_date, end_date)
            else:
                df = get_stock_bars_range(symbol, interval, start_date, end_date)
            symbols_payload[symbol] = {
                "available": True,
                "reason": None,
                "entry_utc": entry_ts.isoformat() if entry_ts is not None else None,
                "entry_is_estimated": entry_is_estimated,
                "interval": interval,
                "points": _thin_points(df),
            }
        except Exception as e:
            # A single symbol's history not being fetchable (e.g. Alpaca
            # has no bars yet for a just-listed ticker) is never a reason
            # to drop every other position's chart.
            symbols_payload[symbol] = {
                "available": False,
                "reason": f"{type(e).__name__}: {e}",
                "entry_utc": entry_ts.isoformat() if entry_ts is not None else None,
                "entry_is_estimated": entry_is_estimated,
                "interval": None,
                "points": [],
            }

    return {"available": True, "reason": None, "symbols": symbols_payload}


# The live stock workflow's --exit-threshold (see
# .github/workflows/paper-trade-stocks.yml) - rule_based/ml_filtered sell
# when price recovers to this far *above* its own 20-period SMA. Not
# read from the workflow file itself (that would need a YAML-parsing
# dependency this project doesn't otherwise have just for a display
# label); if that flag's value ever changes, this constant needs a
# matching manual update, same as dip_threshold/profit_target elsewhere
# in this file already require.
RULE_BASED_EXIT_THRESHOLD = 0.02

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

    Same best-effort-per-symbol contract as build_position_price_histories:
    one ticker's fetch failing (or not having 20 bars of trailing history
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

    now_utc = dt.datetime.now(dt.timezone.utc)
    start_date = (now_utc - dt.timedelta(days=SMA_INDICATOR_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    end_date = (now_utc + dt.timedelta(days=1)).strftime("%Y-%m-%d")
    symbols_payload: dict[str, dict] = {}

    for p in positions:
        symbol = p["symbol"]
        strategy = attribute_position_strategy(trades_df, symbol)
        if strategy not in ("rule_based", "ml_filtered"):
            continue

        try:
            if p["is_crypto"]:
                df = get_crypto_bars_range(_crypto_alpaca_symbol(symbol), SMA_INDICATOR_BAR_INTERVAL, start_date, end_date)
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

    relaunch = find_account_relaunch(equity_df)
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

    position_history_payload = build_position_price_histories(live_result, trades_df)
    (out_dir / "position_history.json").write_text(json.dumps(position_history_payload, indent=2))

    position_indicators_payload = build_position_sma_indicators(live_result, trades_df)
    (out_dir / "position_indicators.json").write_text(json.dumps(position_indicators_payload, indent=2))

    if trades_df is not None and not trades_df.empty:
        recent = trades_df.sort_values("timestamp_utc", ascending=False).head(MAX_TRADES_PUBLISHED)
        trades_payload = {
            "available": True,
            "trades": [
                {
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
                for _, row in recent.iterrows()
            ],
        }
    else:
        trades_payload = {"available": False, "trades": []}
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

    print(f"Wrote dashboard/positions/position_history/position_indicators/trades/equity JSON to {out_dir}/")


if __name__ == "__main__":
    main()
