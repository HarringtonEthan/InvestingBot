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

Writes four files into --out-dir (default site/data/):
  - dashboard.json: account totals (cash/equity/buying power) plus a full
    Today/This Week/This Month/All-Time breakdown - the numbers behind
    every slot-machine reel and stat tile on the page.
  - positions.json: current open positions (crypto + stocks), only
    populated with --live-positions (same opt-in flag visualize_log.py
    already uses) - a read-only Alpaca query, never an order.
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


def period_bounds(now_utc: dt.datetime) -> dict[str, tuple[dt.datetime, dt.datetime]]:
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
    """
    now_et = now_utc.astimezone(ET)
    today_start_et = now_et.replace(hour=0, minute=0, second=0, microsecond=0)
    # Monday is weekday() == 0 - subtract however many days since Monday
    # to land on this week's own Monday, at midnight ET.
    week_start_et = today_start_et - dt.timedelta(days=today_start_et.weekday())
    month_start_et = today_start_et.replace(day=1)
    return {
        "today": (today_start_et.astimezone(dt.timezone.utc), now_utc),
        "week": (week_start_et.astimezone(dt.timezone.utc), now_utc),
        "month": (month_start_et.astimezone(dt.timezone.utc), now_utc),
    }


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
        if len(confirmed_sells):
            best = confirmed_sells.loc[confirmed_sells["realized_pnl_usd"].idxmax()]
            worst = confirmed_sells.loc[confirmed_sells["realized_pnl_usd"].idxmin()]
            result["best_trade"] = _trade_summary(best)
            result["worst_trade"] = _trade_summary(worst)

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


def attribute_position_strategy(trades_df: pd.DataFrame | None, ticker: str) -> str | None:
    """
    Best-effort guess at which strategy currently holds a given open
    position: the most recent BUY logged for this ticker, as long as no
    SELL has been logged for it since (a SELL after that BUY would mean
    the position shown live isn't the one that BUY opened - e.g. it was
    closed and manually re-bought outside the bot). Alpaca's own position
    data has no concept of "strategy" at all (that's purely this
    project's own bookkeeping), so None ("unknown") is the honest answer
    whenever the trade log doesn't clearly support a better one - never
    guessed from the ticker alone.
    """
    if trades_df is None or trades_df.empty:
        return None
    ticker_rows = trades_df[trades_df["ticker"] == ticker].sort_values("timestamp_utc")
    if ticker_rows.empty:
        return None
    last_buy = ticker_rows[ticker_rows["action"] == "BUY"]
    if last_buy.empty:
        return None
    last_buy_ts = last_buy.iloc[-1]["timestamp_utc"]
    later_sell = ticker_rows[(ticker_rows["action"] == "SELL") & (ticker_rows["timestamp_utc"] > last_buy_ts)]
    if not later_sell.empty:
        return None
    return last_buy.iloc[-1]["strategy"]


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

    bounds = period_bounds(now_utc)
    periods = {
        "today": summarize_period("Today", bounds["today"][0], bounds["today"][1], equity_df, trades_df, unrealized_total, unrealized_by_class),
        "week": summarize_period("This Week", bounds["week"][0], bounds["week"][1], equity_df, trades_df, unrealized_total, unrealized_by_class),
        "month": summarize_period("This Month", bounds["month"][0], bounds["month"][1], equity_df, trades_df, unrealized_total, unrealized_by_class),
        "all_time": summarize_period("All Time", None, now_utc, equity_df, trades_df, unrealized_total, unrealized_by_class),
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
        "periods": periods,
        "methodology": {
            "baseline": "each period's starting value is the last known account equity at or before that period's own start (carried forward from whenever it was last logged, not a fixed dollar amount) - all_time starts from the very first row ever logged, with no hardcoded baseline",
            "num_trades": "counts only confirmed-fill SELL executions (completed round trips); submitted-but-unconfirmed and not-placed orders are tracked separately (see num_buys/num_unconfirmed/num_not_placed) and never counted as a trade",
            "realized_pnl": "computed only from confirmed fills; a submitted-but-unconfirmed order's price is a decision-time estimate, not treated as realized",
        },
    }

    (out_dir / "dashboard.json").write_text(json.dumps(dashboard, indent=2))

    positions_payload = build_positions_payload(live_result, trades_df)
    (out_dir / "positions.json").write_text(json.dumps(positions_payload, indent=2))

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

    print(f"Wrote dashboard/positions/trades/equity JSON to {out_dir}/")


if __name__ == "__main__":
    main()
