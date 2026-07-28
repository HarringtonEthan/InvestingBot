"""
Turns the equity/trade logs (logs/equity_log_crypto.csv +
logs/equity_log_stocks.csv, and the trade_log equivalents - see
live_trade.py's --log-suffix) into a dashboard chart - the numbers in
those CSVs are accurate but not exactly readable at a glance, especially
once there's weeks of rows in them.

Five panels:
  1. Net account gain/loss over time (whole account, both asset classes
     combined - this is the one true "how much has this account actually
     made" figure) - equity minus the *first* value in logs/equity_log.csv,
     so it reads directly as "+$X" or "-$X" instead of a raw dollar
     balance. Note the baseline is whenever equity logging started, not
     necessarily when the account was funded - trades placed before that
     point (or before this log format existed) aren't reflected in the
     baseline, only in what happens after it.
  2/3. Cumulative realized P&L from executed SELL trades, crypto and
     stocks shown SEPARATELY (not summed) - one strategy's mean-reversion
     rule looks nothing like the other's day-trading rule, so blending
     their P&L into one line would hide whether either one is actually
     working. Approximate: (sell price - entry price) * qty sold,
     ignoring the exact fee Alpaca charged that trade. If any trade has a
     note in trade_log.csv's `notes` column (e.g. flagging it as inflated
     by a since-fixed bug, not representative of the strategy's own
     decision quality), a second "excluding flagged trades" line is
     plotted alongside the real one in that asset class's panel - never
     hidden, just distinguished. NOT the same number as panel 1's total
     account P&L, and won't sum to it - trade_log.csv only goes back to
     whenever it was last rebuilt (see the archived-log note in
     docs/AUTOMATION.md), so these panels can't see anything that
     happened before that. Panel 1, built from account equity directly,
     is the authoritative "how much has this account actually made"
     answer; these panels are only ever a read on the specific trades
     they have visibility into.
  4/5. Win/loss count per ticker, crypto and stocks in their own panels
     for the same reason - a ticker's wins/losses are only meaningfully
     compared against tickers running the same strategy. Flagged trades
     are hatched in these panels too, same reasoning as above.

Reads whatever data exists; a strategy that trades rarely (or an asset
class with zero closed trades yet - e.g. right after archiving the log
for a strategy change) will produce a sparse or empty panel, not an
error. By default, doesn't hit the network or place any orders - safe to
run anytime.

Optional: pass --live-positions (needs ALPACA_API_KEY/ALPACA_SECRET_KEY
in the environment) to also show CURRENT unrealized P&L per asset class
on panels 2/3, alongside the realized-trades history - a position that's
never been sold has no realized P&L to plot, but it's very much not
"nothing happening," and the whole-account panel alone doesn't say
whether that's coming from crypto or stocks specifically. This is the
only thing in this script that ever talks to Alpaca; it's a read-only
account/position query, never an order.
"""

# Lets type hints work without issue in this Python version.
from __future__ import annotations

# For parsing command-line flags like --equity-log, --baseline.
import argparse

# matplotlib for the actual chart rendering.
import matplotlib
# "Agg" is a non-interactive backend (no GUI popup) - this runs headlessly
# in CI/terminal, not on a desktop with a display.
matplotlib.use("Agg")
import matplotlib.pyplot as plt
# pandas for reading the CSV logs and doing the date/groupby/cumsum work.
import pandas as pd


def load_csv(paths: list[str]) -> pd.DataFrame | None:
    """
    Reads one or more CSVs sharing the same columns and returns them as
    one combined, chronologically-sorted DataFrame - crypto and stocks
    each write to their own log file now (see live_trade.py's
    --log-suffix) so two workflows never race to commit the same file,
    but a single combined timeline is still what every panel below
    actually wants (e.g. the whole-account equity line doesn't care
    which workflow happened to log a given sample).
    """
    frames = []
    for path in paths:
        try:
            df = pd.read_csv(path)
        except FileNotFoundError:
            # This particular log doesn't exist yet - not an error, just
            # nothing to contribute from this file.
            continue
        if not df.empty:
            frames.append(df)
    if not frames:
        # Every path was missing or empty - genuinely nothing to show.
        return None
    combined = pd.concat(frames, ignore_index=True)
    # Parse the timestamp column into actual datetime objects (in UTC) so
    # it can be used as a proper time axis rather than plain strings.
    combined["timestamp_utc"] = pd.to_datetime(combined["timestamp_utc"], utc=True)
    # Rows from different files won't already be in a single chronological
    # order relative to each other - sort explicitly across all of them.
    return combined.sort_values("timestamp_utc")


def aggregate_unrealized_pnl(positions: list[dict]) -> tuple[float, float]:
    """Sums unrealized_pl across open positions, split into (crypto, stock)
    totals by each position's is_crypto flag - pulled out as its own
    function so the split can be unit-tested without a real Broker/Alpaca
    connection (see tests/fake_broker.py's set_unrealized_pl)."""
    crypto_total = sum(p["unrealized_pl"] for p in positions if p["is_crypto"])
    stock_total = sum(p["unrealized_pl"] for p in positions if not p["is_crypto"])
    return crypto_total, stock_total


def _unrealized_note(unrealized_pnl: float | None) -> str:
    # Shared wording for the live-unrealized annotation, used whether or
    # not this asset class has any realized (closed-trade) history yet -
    # a position that's never been sold still has a real, live number
    # worth showing, just not a "cumulative realized" one.
    if unrealized_pnl is None:
        return ""
    color_word = "gain" if unrealized_pnl >= 0 else "loss"
    return f"Live unrealized {color_word} right now (open positions): {unrealized_pnl:+,.2f}"


def plot_cumulative_pnl(ax, sells: pd.DataFrame, label: str, unrealized_pnl: float | None = None):
    """
    Cumulative realized P&L panel for one asset class - called once for
    crypto, once for stocks, so the two never get blended into one
    number the way a single shared panel used to. `unrealized_pnl`, if
    given (from --live-positions), is the CURRENT combined unrealized
    P&L of every open position in this asset class right now - shown
    alongside the realized-trades history, never replacing it, since a
    position that's never been sold has no realized P&L to plot but is
    very much not "nothing happening."
    """
    if sells.empty:
        ax.set_title(f"{label}: cumulative realized P&L (no closed trades yet)")
        ax.text(0.5, 0.5, f"No executed {label} SELL trades yet", ha="center", va="center")
        note = _unrealized_note(unrealized_pnl)
        if note:
            color = "tab:green" if unrealized_pnl >= 0 else "tab:red"
            ax.text(0.5, 0.35, note, ha="center", va="center", color=color, fontweight="bold")
        return

    # Running total of realized P&L, in chronological trade order.
    cum_pnl = sells.set_index("timestamp_utc")["realized_pnl_usd"].cumsum()
    color = "tab:green" if cum_pnl.iloc[-1] >= 0 else "tab:red"
    has_flagged = sells["flagged"].any()
    # marker="o" so a single trade (a single point - nothing to "step"
    # between yet) still shows up as something visible rather than an
    # empty-looking plot.
    ax.step(cum_pnl.index, cum_pnl.values, where="post", color=color, marker="o",
            label="All trades" if has_flagged else None)
    ax.annotate(
        f"{cum_pnl.iloc[-1]:+,.2f}",
        xy=(cum_pnl.index[-1], cum_pnl.iloc[-1]),
        xytext=(8, 0), textcoords="offset points",
        fontweight="bold", color=color, va="center",
    )

    if has_flagged:
        # A second line showing cumulative P&L with flagged
        # (unrepresentative) trades excluded entirely - plotted
        # alongside, never replacing, the full "all trades" line above.
        clean = sells[~sells["flagged"]]
        if not clean.empty:
            cum_clean = clean.set_index("timestamp_utc")["realized_pnl_usd"].cumsum()
            clean_color = "tab:blue"
            ax.step(cum_clean.index, cum_clean.values, where="post", color=clean_color,
                    marker="s", linestyle="--", label="Excluding flagged trades")
            ax.annotate(
                f"{cum_clean.iloc[-1]:+,.2f}",
                xy=(cum_clean.index[-1], cum_clean.iloc[-1]),
                xytext=(8, -14), textcoords="offset points",
                fontweight="bold", color=clean_color, va="center",
            )
        ax.legend(loc="upper left", fontsize=8)

    ax.axhline(0, color="gray", linewidth=0.8)
    ax.set_title(f"{label}: cumulative realized P&L (trades in this log only)")
    ax.set_ylabel("Realized P&L ($)")
    note = _unrealized_note(unrealized_pnl)
    if note:
        note_color = "tab:green" if unrealized_pnl >= 0 else "tab:red"
        ax.text(0.02, 0.02, note, transform=ax.transAxes, ha="left", va="bottom",
                color=note_color, fontweight="bold", fontsize=9)
    if len(cum_pnl) == 1:
        # A single data point gives matplotlib's date auto-scaling nothing
        # to infer a sensible range from - it can default to spanning
        # several *years*. Pad a fixed window around the one point instead.
        pad = pd.Timedelta(hours=1)
        ax.set_xlim(cum_pnl.index[0] - pad, cum_pnl.index[0] + pad)


def plot_win_loss(ax, sells: pd.DataFrame, label: str):
    """
    Win/loss-per-ticker panel for one asset class - called once for
    crypto, once for stocks, so a stock ticker's win rate is never
    compared side by side with a crypto ticker running a completely
    different strategy.
    """
    if sells.empty:
        ax.set_title(f"{label}: win/loss per ticker (no closed trades yet)")
        ax.text(0.5, 0.5, f"No executed {label} SELL trades yet", ha="center", va="center")
        return

    is_win = sells["realized_pnl_usd"] > 0
    tickers = sorted(sells["ticker"].unique())

    def counts(mask):
        # Count trades matching this boolean mask, grouped by ticker;
        # reindex ensures every known ticker gets a bar (0 if it had
        # no trades in this category) instead of just being omitted.
        return sells[mask].groupby("ticker").size().reindex(tickers, fill_value=0)

    # Split every trade into 4 buckets: win/loss crossed with
    # flagged/not-flagged, so the stacked bar chart below can render
    # flagged trades with a distinct hatch pattern.
    wins_clean = counts(is_win & ~sells["flagged"])
    wins_flagged = counts(is_win & sells["flagged"])
    losses_clean = counts(~is_win & ~sells["flagged"])
    losses_flagged = counts(~is_win & sells["flagged"])

    x = range(len(tickers))
    # Build the stacked bars one segment at a time, tracking `bottom`
    # (the running height already stacked) so each new segment starts
    # where the previous one left off instead of overlapping it.
    ax.bar(x, wins_clean.values, label="Win", color="tab:green")
    bottom = wins_clean.values
    if wins_flagged.sum() > 0:
        ax.bar(x, wins_flagged.values, bottom=bottom, label="Win (flagged - see notes)",
               color="tab:green", hatch="//", edgecolor="black")
        bottom = bottom + wins_flagged.values
    ax.bar(x, losses_clean.values, bottom=bottom, label="Loss", color="tab:red")
    bottom = bottom + losses_clean.values
    if losses_flagged.sum() > 0:
        ax.bar(x, losses_flagged.values, bottom=bottom, label="Loss (flagged - see notes)",
               color="tab:red", hatch="//", edgecolor="black")

    ax.set_xticks(list(x))
    ax.set_xticklabels(tickers, rotation=45, ha="right")
    title = f"{label}: win/loss per ticker"
    if sells["flagged"].any():
        title += " - hatched = flagged"
    ax.set_title(title)
    ax.set_ylabel("Trades")
    ax.legend(fontsize=8)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--equity-log", nargs="+", default=["logs/equity_log_crypto.csv", "logs/equity_log_stocks.csv"],
                         help="one or more equity log files, combined into one timeline - crypto and "
                              "stocks each write to their own file (see live_trade.py's --log-suffix) "
                              "so two workflows never race to commit the same one")
    parser.add_argument("--trade-log", nargs="+", default=["logs/trade_log_crypto.csv", "logs/trade_log_stocks.csv"],
                         help="one or more trade log files, combined the same way as --equity-log")
    parser.add_argument("--out", default="results/trade_dashboard.png")
    parser.add_argument("--baseline", type=float, default=None,
                         help="account value to measure net gain/loss from, e.g. --baseline 100000 "
                              "for your original funding amount. Without this, the baseline is "
                              "whatever the first row of --equity-log happens to be - which is "
                              "wherever equity logging started, not necessarily when the account "
                              "was funded, so it can understate gains or losses that happened "
                              "before logging began.")
    parser.add_argument("--live-positions", action="store_true",
                         help="pull current open positions from Alpaca (needs ALPACA_API_KEY/"
                              "ALPACA_SECRET_KEY) and show live unrealized P&L per asset class "
                              "on panels 2/3, alongside the realized-trades history. Read-only - "
                              "never places an order.")
    args = parser.parse_args()

    equity_df = load_csv(args.equity_log)
    trade_df = load_csv(args.trade_log)

    crypto_unrealized = None
    stock_unrealized = None
    if args.live_positions:
        # Imported here, not at module level, so running this script
        # without --live-positions never requires alpaca-py to be
        # importable or ALPACA_* env vars to be set at all.
        from src.broker import Broker
        broker = Broker(allow_live=True)  # read-only query - this script never places orders
        positions = broker.get_all_positions()
        crypto_unrealized, stock_unrealized = aggregate_unrealized_pnl(positions)

    sells = pd.DataFrame()
    if trade_df is not None:
        # Only rows that were an actual executed SELL count toward
        # realized P&L - a HOLD or a dry-run (order_placed == False)
        # never changed the account, so including it here would be wrong.
        # order_placed is read back from CSV as the string "True"/"False",
        # not a real bool, hence the explicit .astype(str) comparison.
        sells = trade_df[
            (trade_df["action"] == "SELL") & (trade_df["order_placed"].astype(str) == "True")
        ].copy()
        if not sells.empty:
            # Approximate realized profit/loss per trade: how much the
            # sell price differs from the average entry price, times how
            # many units were held going into the sell.
            sells["realized_pnl_usd"] = (
                sells["price_usd"] - sells["avg_entry_price_usd"]
            ) * sells["position_qty_before"]
            # Older trade_log.csv files (before "notes" existed) won't have
            # this column at all - treat that the same as "nothing flagged".
            if "notes" in sells.columns:
                # A row counts as flagged if its notes field is present
                # (not NaN) and isn't just blank/whitespace.
                sells["flagged"] = sells["notes"].notna() & (sells["notes"].astype(str).str.strip() != "")
            else:
                sells["flagged"] = False

    # Splitting by asset_class here, once, is what lets every panel below
    # just call the same crypto/stock-agnostic helper twice - if sells
    # itself came back empty (no trade log at all), both splits are
    # empty too, and the helpers already handle that case cleanly.
    if not sells.empty and "asset_class" in sells.columns:
        crypto_sells = sells[sells["asset_class"] == "crypto"]
        stock_sells = sells[sells["asset_class"] == "stock"]
    else:
        crypto_sells = pd.DataFrame()
        stock_sells = pd.DataFrame()

    # A 2-column grid: row 1 spans both columns (the one whole-account
    # figure), rows 2-3 are crypto | stocks side by side.
    fig, axes = plt.subplot_mosaic(
        [["net", "net"], ["crypto_pnl", "stock_pnl"], ["crypto_winloss", "stock_winloss"]],
        figsize=(14, 14),
    )

    # ---- Panel 1: net account gain/loss over time (whole account) ----
    ax = axes["net"]
    if equity_df is not None:
        if args.baseline is not None:
            # Caller supplied an explicit baseline (e.g. the true funding
            # amount) - use it directly instead of guessing from the log.
            baseline = args.baseline
            baseline_label = "since baseline"
        else:
            # No explicit baseline given - fall back to the first value
            # ever recorded in the equity log (whenever logging happened
            # to start, not necessarily when the account was funded).
            baseline = equity_df["portfolio_value_usd"].iloc[0]
            baseline_label = "since tracking began"
        # Every equity value minus the baseline - turns a raw dollar
        # balance into a directly-readable "+$X" or "-$X" gain/loss series.
        net = equity_df["portfolio_value_usd"] - baseline
        color = "tab:green" if net.iloc[-1] >= 0 else "tab:red"
        ax.plot(equity_df["timestamp_utc"], net, color=color)
        # A horizontal reference line at zero, so it's obvious at a
        # glance whether the line is currently above or below break-even.
        ax.axhline(0, color="gray", linewidth=0.8)
        ax.set_title(f"Net account gain/loss {baseline_label} (baseline ${baseline:,.2f}) - whole account, crypto + stocks combined")
        ax.set_ylabel("Net gain/loss ($)")
        # Label the final point directly on the chart with its exact
        # value, so the current number doesn't require squinting at the axis.
        ax.annotate(
            f"{net.iloc[-1]:+,.2f}",
            xy=(equity_df["timestamp_utc"].iloc[-1], net.iloc[-1]),
            xytext=(8, 0), textcoords="offset points",
            fontweight="bold", color=color, va="center",
        )
    else:
        # No equity log yet - show an empty panel with an explanatory message.
        ax.set_title("Net account gain/loss (no data yet)")
        ax.text(0.5, 0.5, "No equity log data found", ha="center", va="center")

    # ---- Panels 2/3: cumulative realized P&L, crypto and stocks separately ----
    plot_cumulative_pnl(axes["crypto_pnl"], crypto_sells, "Crypto", unrealized_pnl=crypto_unrealized)
    plot_cumulative_pnl(axes["stock_pnl"], stock_sells, "Stocks", unrealized_pnl=stock_unrealized)

    # ---- Panels 4/5: win/loss per ticker, crypto and stocks separately ----
    plot_win_loss(axes["crypto_winloss"], crypto_sells, "Crypto")
    plot_win_loss(axes["stock_winloss"], stock_sells, "Stocks")

    # Adjust spacing so the panels' titles/labels don't overlap each
    # other, then write the final image to disk.
    fig.tight_layout()
    fig.savefig(args.out, dpi=120)
    print(f"Saved dashboard to {args.out}")


if __name__ == "__main__":
    main()
