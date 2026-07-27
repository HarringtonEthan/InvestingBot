"""
Turns logs/equity_log.csv and logs/trade_log.csv into a dashboard chart -
the numbers in those CSVs are accurate but not exactly readable at a
glance, especially once there's weeks of rows in them.

Three panels:
  1. Net account gain/loss over time - equity minus the *first* value in
     logs/equity_log.csv, so it reads directly as "+$X" or "-$X" instead
     of a raw dollar balance. Note the baseline is whenever equity
     logging started, not necessarily when the account was funded -
     trades placed before that point (or before this log format existed)
     aren't reflected in the baseline, only in what happens after it.
  2. Cumulative realized P&L from executed SELL trades - isolates whether
     the *trades themselves* are profitable, separate from e.g. paper cash
     just sitting there or unrealized swings on open positions. Approximate:
     (sell price - entry price) * qty sold, ignoring the exact fee Alpaca
     charged that trade. If any trade has a note in trade_log.csv's
     `notes` column (e.g. flagging it as inflated by a since-fixed bug,
     not representative of the strategy's own decision quality), a
     second "excluding flagged trades" line is plotted alongside the
     real one - never hidden, just distinguished, so both the honest
     full history and the "how is the strategy itself doing" view are
     visible at once. NOT the same number as panel 1's total account
     P&L, and won't sum to it - trade_log.csv only goes back to whenever
     it was last rebuilt (see the archived-log note in docs/AUTOMATION.md), so
     this panel can't see anything that happened before that. Panel 1,
     built from account equity directly, is the authoritative "how much
     has this account actually made" answer; this panel is only ever a
     read on the specific trades it has visibility into.
  3. Win/loss count per ticker, from the same executed SELL trades - which
     tickers are actually working vs. not. Flagged trades are hatched in
     this panel too, same reasoning as above.

Reads whatever data exists; a strategy that trades rarely will produce a
sparse panel 2/3, not an error. Doesn't hit the network or place any
orders - safe to run anytime.
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


def load_csv(path: str) -> pd.DataFrame | None:
    try:
        df = pd.read_csv(path)
    except FileNotFoundError:
        # Log file doesn't exist yet (e.g. a fresh checkout before the
        # bot has ever run) - not an error, just "no data yet".
        return None
    if df.empty:
        # File exists but has no data rows (e.g. only a header, or
        # completely empty) - same "nothing to show" case as above.
        return None
    # Parse the timestamp column into actual datetime objects (in UTC) so
    # it can be used as a proper time axis rather than plain strings.
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    # Rows should already be roughly chronological, but sort explicitly to
    # be safe regardless of how they were appended.
    return df.sort_values("timestamp_utc")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--equity-log", default="logs/equity_log.csv")
    parser.add_argument("--trade-log", default="logs/trade_log.csv")
    parser.add_argument("--out", default="results/trade_dashboard.png")
    parser.add_argument("--baseline", type=float, default=None,
                         help="account value to measure net gain/loss from, e.g. --baseline 100000 "
                              "for your original funding amount. Without this, the baseline is "
                              "whatever the first row of --equity-log happens to be - which is "
                              "wherever equity logging started, not necessarily when the account "
                              "was funded, so it can understate gains or losses that happened "
                              "before logging began.")
    args = parser.parse_args()

    equity_df = load_csv(args.equity_log)
    trade_df = load_csv(args.trade_log)

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

    # Three stacked panels sharing one figure, one axes object per panel.
    fig, axes = plt.subplots(3, 1, figsize=(10, 12))

    # ---- Panel 1: net account gain/loss over time ----
    ax = axes[0]
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
        ax.set_title(f"Net account gain/loss {baseline_label} (baseline ${baseline:,.2f})")
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
        ax.text(0.5, 0.5, "logs/equity_log.csv is empty or missing", ha="center", va="center")

    # ---- Panel 2: cumulative realized P&L from actual trades ----
    ax = axes[1]
    if not sells.empty:
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
        ax.set_title("Cumulative realized P&L, trades in this log only (not total account P&L - see panel above)")
        ax.set_ylabel("Realized P&L ($)")
        # A single data point gives matplotlib's date auto-scaling nothing
        # to infer a sensible range from - it can default to spanning
        # several *years*. Anchor the x-axis to the equity log's actual
        # time range (or a fixed pad around the one point) instead.
        if equity_df is not None:
            ax.set_xlim(equity_df["timestamp_utc"].min(), equity_df["timestamp_utc"].max())
        elif len(cum_pnl) == 1:
            pad = pd.Timedelta(hours=1)
            ax.set_xlim(cum_pnl.index[0] - pad, cum_pnl.index[0] + pad)
    else:
        ax.set_title("Cumulative realized P&L from executed trades (no closed trades yet)")
        ax.text(0.5, 0.5, "No executed SELL trades in logs/trade_log.csv yet", ha="center", va="center")

    # ---- Panel 3: win/loss count per ticker ----
    ax = axes[2]
    if not sells.empty:
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
        title = "Win/loss count per ticker (executed trades)"
        if sells["flagged"].any():
            title += " - hatched = flagged, see trade_log.csv notes"
        ax.set_title(title)
        ax.set_ylabel("Trades")
        ax.legend(fontsize=8)
    else:
        ax.set_title("Win/loss count per ticker (no closed trades yet)")
        ax.text(0.5, 0.5, "No executed SELL trades in logs/trade_log.csv yet", ha="center", va="center")

    # Adjust spacing so the 3 stacked panels' titles/labels don't overlap
    # each other, then write the final image to disk.
    fig.tight_layout()
    fig.savefig(args.out, dpi=120)
    print(f"Saved dashboard to {args.out}")


if __name__ == "__main__":
    main()
