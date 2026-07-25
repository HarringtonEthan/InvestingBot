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
     visible at once.
  3. Win/loss count per ticker, from the same executed SELL trades - which
     tickers are actually working vs. not. Flagged trades are hatched in
     this panel too, same reasoning as above.

Reads whatever data exists; a strategy that trades rarely will produce a
sparse panel 2/3, not an error. Doesn't hit the network or place any
orders - safe to run anytime.
"""

from __future__ import annotations

import argparse

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


def load_csv(path: str) -> pd.DataFrame | None:
    try:
        df = pd.read_csv(path)
    except FileNotFoundError:
        return None
    if df.empty:
        return None
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
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
        sells = trade_df[
            (trade_df["action"] == "SELL") & (trade_df["order_placed"].astype(str) == "True")
        ].copy()
        if not sells.empty:
            sells["realized_pnl_usd"] = (
                sells["price_usd"] - sells["avg_entry_price_usd"]
            ) * sells["position_qty_before"]
            # Older trade_log.csv files (before "notes" existed) won't have
            # this column at all - treat that the same as "nothing flagged".
            if "notes" in sells.columns:
                sells["flagged"] = sells["notes"].notna() & (sells["notes"].astype(str).str.strip() != "")
            else:
                sells["flagged"] = False

    fig, axes = plt.subplots(3, 1, figsize=(10, 12))

    ax = axes[0]
    if equity_df is not None:
        if args.baseline is not None:
            baseline = args.baseline
            baseline_label = "since baseline"
        else:
            baseline = equity_df["portfolio_value_usd"].iloc[0]
            baseline_label = "since tracking began"
        net = equity_df["portfolio_value_usd"] - baseline
        color = "tab:green" if net.iloc[-1] >= 0 else "tab:red"
        ax.plot(equity_df["timestamp_utc"], net, color=color)
        ax.axhline(0, color="gray", linewidth=0.8)
        ax.set_title(f"Net account gain/loss {baseline_label} (baseline ${baseline:,.2f})")
        ax.set_ylabel("Net gain/loss ($)")
        ax.annotate(
            f"{net.iloc[-1]:+,.2f}",
            xy=(equity_df["timestamp_utc"].iloc[-1], net.iloc[-1]),
            xytext=(8, 0), textcoords="offset points",
            fontweight="bold", color=color, va="center",
        )
    else:
        ax.set_title("Net account gain/loss (no data yet)")
        ax.text(0.5, 0.5, "logs/equity_log.csv is empty or missing", ha="center", va="center")

    ax = axes[1]
    if not sells.empty:
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
        ax.set_title("Cumulative realized P&L from executed trades")
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

    ax = axes[2]
    if not sells.empty:
        is_win = sells["realized_pnl_usd"] > 0
        tickers = sorted(sells["ticker"].unique())

        def counts(mask):
            return sells[mask].groupby("ticker").size().reindex(tickers, fill_value=0)

        wins_clean = counts(is_win & ~sells["flagged"])
        wins_flagged = counts(is_win & sells["flagged"])
        losses_clean = counts(~is_win & ~sells["flagged"])
        losses_flagged = counts(~is_win & sells["flagged"])

        x = range(len(tickers))
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

    fig.tight_layout()
    fig.savefig(args.out, dpi=120)
    print(f"Saved dashboard to {args.out}")


if __name__ == "__main__":
    main()
