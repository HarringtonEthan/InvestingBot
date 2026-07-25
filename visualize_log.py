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
     charged that trade.
  3. Win/loss count per ticker, from the same executed SELL trades - which
     tickers are actually working vs. not.

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

    fig, axes = plt.subplots(3, 1, figsize=(10, 12))

    ax = axes[0]
    if equity_df is not None:
        baseline = equity_df["portfolio_value_usd"].iloc[0]
        net = equity_df["portfolio_value_usd"] - baseline
        color = "tab:green" if net.iloc[-1] >= 0 else "tab:red"
        ax.plot(equity_df["timestamp_utc"], net, color=color)
        ax.axhline(0, color="gray", linewidth=0.8)
        ax.set_title(f"Net account gain/loss since tracking began (baseline ${baseline:,.2f})")
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
        # marker="o" so a single trade (a single point - nothing to "step"
        # between yet) still shows up as something visible rather than an
        # empty-looking plot.
        ax.step(cum_pnl.index, cum_pnl.values, where="post", color=color, marker="o")
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
        ax.annotate(
            f"{cum_pnl.iloc[-1]:+,.2f}",
            xy=(cum_pnl.index[-1], cum_pnl.iloc[-1]),
            xytext=(8, 0), textcoords="offset points",
            fontweight="bold", color=color, va="center",
        )
    else:
        ax.set_title("Cumulative realized P&L from executed trades (no closed trades yet)")
        ax.text(0.5, 0.5, "No executed SELL trades in logs/trade_log.csv yet", ha="center", va="center")

    ax = axes[2]
    if not sells.empty:
        wins = sells[sells["realized_pnl_usd"] > 0].groupby("ticker").size()
        losses = sells[sells["realized_pnl_usd"] <= 0].groupby("ticker").size()
        tickers = sorted(set(wins.index) | set(losses.index))
        wins = wins.reindex(tickers, fill_value=0)
        losses = losses.reindex(tickers, fill_value=0)
        x = range(len(tickers))
        ax.bar(x, wins.values, label="Win", color="tab:green")
        ax.bar(x, losses.values, bottom=wins.values, label="Loss", color="tab:red")
        ax.set_xticks(list(x))
        ax.set_xticklabels(tickers, rotation=45, ha="right")
        ax.set_title("Win/loss count per ticker (executed trades)")
        ax.set_ylabel("Trades")
        ax.legend()
    else:
        ax.set_title("Win/loss count per ticker (no closed trades yet)")
        ax.text(0.5, 0.5, "No executed SELL trades in logs/trade_log.csv yet", ha="center", va="center")

    fig.tight_layout()
    fig.savefig(args.out, dpi=120)
    print(f"Saved dashboard to {args.out}")


if __name__ == "__main__":
    main()
