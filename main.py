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

from __future__ import annotations

import argparse

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from src.backtest import run_backtest
from src.data import get_price_data
from src.features import add_features
from src.model import train_model
from src.strategies import buy_and_hold, ml_filtered_dip_buy, rule_based_dip_buy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", default="SPY")
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--split", default="2022-01-01", help="train/test split date")
    parser.add_argument("--end", default="2024-12-31")
    parser.add_argument("--seed", type=int, default=7, help="synthetic-data RNG seed")
    parser.add_argument("--out", default="results/equity_curve.png")
    args = parser.parse_args()

    raw, is_synthetic = get_price_data(args.ticker, args.start, args.end, seed=args.seed)
    label = f"SYNTHETIC data (no live market access) - NOT real {args.ticker} prices" if is_synthetic \
        else f"real {args.ticker} data from Yahoo Finance"
    print(f"Data source: {label}")
    print(f"Rows: {len(raw)}  Range: {raw.index.min().date()} -> {raw.index.max().date()}\n")

    df = add_features(raw)

    train_df = df[df.index < args.split]
    test_df = df[df.index >= args.split]
    if len(train_df) < 100 or len(test_df) < 50:
        raise SystemExit("Not enough data on one side of the train/test split; widen --start/--end.")

    model, threshold, train_scores = train_model(train_df)
    print(f"ML dip-filter trained on {len(train_df)} rows.")
    print(
        f"Train-set predicted bounce-probability range: "
        f"[{train_scores.min():.3f}, {train_scores.max():.3f}], "
        f"calibrated threshold (75th pct): {threshold:.3f}\n"
    )

    strategies = {
        "Buy & Hold": buy_and_hold(test_df),
        "Rule-based dip buy": rule_based_dip_buy(test_df),
        "ML-filtered dip buy": ml_filtered_dip_buy(test_df, model, threshold),
    }

    results = {}
    print(f"{'Strategy':<22}{'Total Ret':>12}{'Ann. Ret':>12}{'Ann. Vol':>12}{'Sharpe':>10}{'Max DD':>10}{'Trades':>9}")
    for name, position in strategies.items():
        result = run_backtest(test_df["Close"], position)
        results[name] = result
        print(
            f"{name:<22}{result.total_return:>11.1%} {result.annualized_return:>11.1%} "
            f"{result.annualized_vol:>11.1%} {result.sharpe:>10.2f} {result.max_drawdown:>10.1%} {result.num_trades:>9}"
        )

    if is_synthetic:
        print(
            "\nNOTE: these numbers are from synthetic data and prove nothing about "
            "real markets. Re-run with real network access before drawing any conclusions."
        )

    plt.figure(figsize=(10, 6))
    for name, result in results.items():
        plt.plot(result.equity_curve.index, result.equity_curve.values, label=name)
    title_suffix = " (SYNTHETIC DATA)" if is_synthetic else ""
    plt.title(f"{args.ticker} strategy comparison{title_suffix}")
    plt.xlabel("Date")
    plt.ylabel("Portfolio value ($)")
    plt.legend()
    plt.tight_layout()
    plt.savefig(args.out, dpi=120)
    print(f"\nChart saved to {args.out}")


if __name__ == "__main__":
    main()
