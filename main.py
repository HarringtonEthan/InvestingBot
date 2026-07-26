"""
Buy-the-dip stock strategy backtest.

Pulls real daily price data for a ticker (falling back to clearly-labeled
synthetic data if there's no network access), splits it into a train
period (used only to fit the ML dip-filter and calibrate its threshold)
and a held-out test period, then compares three strategies on the test
period:

  1. Buy and hold
  2. Rule-based dip buying (buy when price is X% below its 20-day SMA,
     sell on recovery)
  3. The same rule, filtered by an ML model that only takes the dip-buy
     signal when its predicted bounce-probability clears a threshold
     calibrated from training data

This is a research/backtesting tool. It does not place real trades and is
not investment advice. See README.md before ever pointing this at a live
brokerage account.
"""

# Lets type hints work without issue in this Python version.
from __future__ import annotations

# For parsing command-line flags like --ticker, --start, --dip-threshold.
import argparse

# matplotlib for the equity-curve comparison chart.
import matplotlib
# "Agg" is a non-interactive backend (no GUI popup window) - required
# since this runs headlessly in CI/terminal, not on a desktop with a display.
matplotlib.use("Agg")
import matplotlib.pyplot as plt
# pandas is imported but only used implicitly through the DataFrames
# returned by the functions below.
import pandas as pd

# The backtest engine that turns a position series into an equity curve.
from src.backtest import run_backtest
# Loads real (or synthetic fallback) price data.
from src.data import get_price_data
# Computes technical indicator columns from raw price data.
from src.features import add_features
# Trains the ML dip-filter model.
from src.model import train_model
# The five trading strategies being compared.
from src.strategies import (
    bollinger_breakout,
    buy_and_hold,
    dip_buy_profit_target,
    ml_filtered_dip_buy,
    rule_based_dip_buy,
)


def run_for_ticker(ticker: str, args):
    """Runs the full backtest suite for one ticker. Returns True on success, False if skipped."""
    # Fetch price history; is_synthetic tells us whether this is real
    # market data or a fallback fake series (e.g. no network access).
    raw, is_synthetic = get_price_data(ticker, args.start, args.end, interval=args.interval, seed=args.seed)
    label = f"SYNTHETIC data (no live market access) - NOT real {ticker} prices" if is_synthetic \
        else f"real {ticker} data from Yahoo Finance"
    print(f"=== {ticker} ===")
    print(f"Data source: {label}")
    print(f"Rows: {len(raw)}  Range: {raw.index.min().date()} -> {raw.index.max().date()}\n")

    # Add all the technical indicator columns (SMA, RSI, etc.) used by
    # both the rule-based strategies and the ML model.
    df = add_features(raw)

    # Split into a training window (everything before the split date) and
    # a held-out test window (everything on/after it) - the ML model only
    # ever sees the training half during fitting.
    train_df = df[df.index < args.split]
    test_df = df[df.index >= args.split]
    if len(train_df) < 100 or len(test_df) < 50:
        # Not enough rows on one side to produce a meaningful result -
        # skip this ticker rather than run a backtest on too little data.
        print(f"Not enough data on one side of the train/test split for {ticker}; widen --start/--end. Skipping.\n")
        return False

    # Fit the ML dip-filter purely on the training period, and get back
    # its calibrated confidence threshold too.
    model, threshold, train_scores = train_model(train_df)
    print(f"ML dip-filter trained on {len(train_df)} rows.")
    print(
        f"Train-set predicted bounce-probability range: "
        f"[{train_scores.min():.3f}, {train_scores.max():.3f}], "
        f"calibrated threshold (75th pct): {threshold:.3f}\n"
    )

    # Run every strategy on the same held-out test period, each producing
    # a position series (fraction invested per day).
    strategies = {
        "Buy & Hold": buy_and_hold(test_df),
        "Rule-based dip buy": rule_based_dip_buy(test_df, dip_threshold=args.dip_threshold),
        "ML-filtered dip buy": ml_filtered_dip_buy(test_df, model, threshold, dip_threshold=args.dip_threshold),
        "Day trading (profit target)": dip_buy_profit_target(
            test_df, dip_threshold=args.dip_threshold,
            profit_target=args.profit_target, stop_loss=args.stop_loss,
        ),
        "Bollinger breakout": bollinger_breakout(
            test_df, bb_window=args.bb_window,
            bb_std=args.bb_std, trend_window=args.trend_window,
        ),
    }

    results = {}
    # Header row for the results table printed to the console.
    print(f"{'Strategy':<28}{'Total Ret':>12}{'Ann. Ret':>12}{'Ann. Vol':>12}{'Sharpe':>10}{'Max DD':>10}{'Trades':>9}")
    for name, position in strategies.items():
        # Turn this strategy's position series into an actual simulated
        # equity curve and performance stats.
        result = run_backtest(test_df["Close"], position, cost_bps=args.cost_bps)
        results[name] = result
        print(
            f"{name:<28}{result.total_return:>11.1%} {result.annualized_return:>11.1%} "
            f"{result.annualized_vol:>11.1%} {result.sharpe:>10.2f} {result.max_drawdown:>10.1%} {result.num_trades:>9}"
        )

    if is_synthetic:
        # Loud, repeated reminder not to mistake fake-data results for
        # anything meaningful about real markets.
        print(
            "\nNOTE: these numbers are from synthetic data and prove nothing about "
            "real markets. Re-run with real network access before drawing any conclusions."
        )

    # When backtesting multiple tickers in one run, give each one its own
    # output filename instead of overwriting the same chart repeatedly.
    out_path = args.out
    if len(args.ticker) > 1:
        # Split "results/equity_curve.png" into stem="results/equity_curve"
        # and ext="png" so the ticker name can be inserted between them.
        stem, _, ext = args.out.rpartition(".")
        # Replace "/" (from crypto tickers like "BTC/USD") since it's not
        # a valid character in a filename.
        safe_ticker = ticker.replace("/", "-")
        out_path = f"{stem}_{safe_ticker}.{ext}" if stem else f"{args.out}_{safe_ticker}"

    # Build the comparison chart: one line per strategy, all sharing the
    # same time axis.
    plt.figure(figsize=(10, 6))
    for name, result in results.items():
        plt.plot(result.equity_curve.index, result.equity_curve.values, label=name)
    title_suffix = " (SYNTHETIC DATA)" if is_synthetic else ""
    plt.title(f"{ticker} strategy comparison{title_suffix}")
    plt.xlabel("Date")
    plt.ylabel("Portfolio value ($)")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_path, dpi=120)
    plt.close()
    print(f"\nChart saved to {out_path}\n")
    return True


def main():
    # __doc__ (this file's module docstring above) becomes the --help text.
    parser = argparse.ArgumentParser(description=__doc__)
    # nargs="+" means one or more tickers can be passed, space-separated.
    parser.add_argument("--ticker", nargs="+", default=["SPY"],
                         help="one or more tickers, space-separated, e.g. --ticker BTC-USD ETH-USD SOL-USD")
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--split", default="2022-01-01", help="train/test split date")
    parser.add_argument("--end", default="2024-12-31")
    parser.add_argument("--interval", default="1d",
                         help="bar size: 1d, 1h, 30m, 15m, 5m. Use an intraday interval to backtest "
                              "day-trading-style strategies - and keep --start recent, since Yahoo "
                              "Finance only keeps a limited window of intraday history.")
    parser.add_argument("--cost-bps", type=float, default=5.0,
                         help="round-trip cost assumption in basis points; crypto fees run higher "
                              "than stocks (try 15-25) so don't leave this at the stock default "
                              "when backtesting day_trading on crypto")
    parser.add_argument("--dip-threshold", type=float, default=-0.02,
                         help="day-trading strategy: dip entry threshold, e.g. -0.02 = 2%% below rolling average")
    parser.add_argument("--profit-target", type=float, default=0.02,
                         help="day-trading strategy: sell once this far above your entry price")
    parser.add_argument("--stop-loss", type=float, default=0.04,
                         help="day-trading strategy: sell if price falls this far below your entry price")
    parser.add_argument("--bb-window", type=int, default=20,
                         help="Bollinger breakout: period for the middle band / trend-loss exit SMA")
    parser.add_argument("--bb-std", type=float, default=2.0,
                         help="Bollinger breakout: standard deviations for the upper band")
    parser.add_argument("--trend-window", type=int, default=200,
                         help="Bollinger breakout: long SMA period required to confirm a breakout")
    parser.add_argument("--seed", type=int, default=7, help="synthetic-data RNG seed")
    parser.add_argument("--out", default="results/equity_curve.png")
    args = parser.parse_args()

    # Run the whole backtest suite once per ticker requested.
    for ticker in args.ticker:
        run_for_ticker(ticker, args)


if __name__ == "__main__":
    # Only run main() when this file is executed directly (e.g.
    # `python main.py`), not when imported as a module elsewhere.
    main()
