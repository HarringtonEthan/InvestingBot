"""
Systematic parameter search for the day-trading (dip buy / profit target /
stop loss) strategy, across multiple tickers at once.

This exists because hand-picking one threshold combination and hoping it's
good is exactly the overfitting trap this whole project has been trying to
avoid. Instead of chasing "the highest backtest number," this:

  - Tests every combination across ALL tickers you give it and reports the
    AVERAGE, not the best single ticker (a combo that only works on one
    coin isn't a real edge, it's luck).
  - Skips combos that trade too rarely to mean anything
    (--min-trades).
  - Writes the full grid to CSV so you can check whether a good result
    sits among other similarly-good neighboring settings (a real signal)
    or is an isolated spike surrounded by bad neighbors (almost always
    noise from testing many combinations, not a real edge).

Still not a substitute for testing the winner on a further, later,
held-out time window before trusting it with anything beyond fake money -
this script tells you what looked best on the period you gave it, not
what will keep working going forward. See walk_forward.py for that next
step.

Data source: crypto tickers pull historical bars from Alpaca first (see
src/data.py's get_price_data_smart()), since Yahoo Finance's ~60-day
intraday history window would otherwise cap any real grid search at a
couple months. Needs ALPACA_API_KEY/ALPACA_SECRET_KEY in your .env, same
as live trading, even though this never places an order.
"""

# Lets type hints work without issue in this Python version.
from __future__ import annotations

# argparse for command-line flags; itertools for generating every
# combination of parameter values to test (the "grid" in grid search).
import argparse
import itertools

# pandas to assemble the results grid and write it out as a CSV.
import pandas as pd
# Loads ALPACA_API_KEY / ALPACA_SECRET_KEY from a local .env file, same
# as live_trade.py - needed here too now that crypto tickers may pull
# real historical bars from Alpaca, not just Yahoo Finance.
from dotenv import load_dotenv

# The backtest engine used to score every parameter combination.
from src.backtest import run_backtest
# Price data loading (Alpaca-first for crypto, Yahoo otherwise); also
# the bars-per-year table for intraday intervals, reused so the Sharpe
# column here is scaled correctly for --interval 5m and similar, not
# silently assuming daily bars.
from src.data import PERIODS_PER_YEAR_24_7, get_price_data_smart
# Technical indicator computation.
from src.features import add_features
# The one strategy this script sweeps parameters for.
from src.strategies import dip_buy_profit_target


def evaluate_combo(test_dfs: dict, dip: float, profit: float, stop: float, cost_bps: float, min_trades: float, periods_per_year: float):
    """
    Backtests one (dip, profit, stop) combination against every ticker in
    test_dfs and averages the results - a single ticker's number never
    gets reported on its own, only ever as part of this cross-ticker
    average (see the module docstring on why). Returns None if the
    combo trades too rarely across the whole set to be filtered out by
    --min-trades before it ever reaches the results table.
    """
    returns, sharpes, trades = [], [], []
    for test_df in test_dfs.values():
        # Run this one parameter combination against every ticker's data.
        position = dip_buy_profit_target(test_df, dip_threshold=dip, profit_target=profit, stop_loss=stop)
        result = run_backtest(test_df["Close"], position, cost_bps=cost_bps, periods_per_year=periods_per_year)
        returns.append(result.total_return)
        if result.sharpe == result.sharpe:  # skip NaN (zero-trade combos)
            # A NaN never equals itself, so this comparison is a compact
            # way to check "is this a real number, not NaN" without
            # importing math.isnan just for this one check.
            sharpes.append(result.sharpe)
        trades.append(result.num_trades)

    avg_trades = sum(trades) / len(trades)
    if avg_trades < min_trades:
        # This combination barely trades at all across the given tickers -
        # too few data points for its return/Sharpe numbers to mean
        # anything, so drop it from the results entirely.
        return None

    return {
        "dip_threshold": dip,
        "profit_target": profit,
        "stop_loss": stop,
        "avg_total_return": sum(returns) / len(returns),
        "avg_sharpe": sum(sharpes) / len(sharpes) if sharpes else float("nan"),
        "avg_trades": avg_trades,
        # The single worst-performing ticker under this combo - a combo
        # that looks great on average but wrecks one ticker is a red flag
        # worth seeing directly, not just averaged away.
        "worst_ticker_return": min(returns),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", nargs="+", required=True, help="e.g. --ticker BTC-USD ETH-USD SOL-USD ...")
    parser.add_argument("--start", required=True)
    parser.add_argument("--split", required=True, help="only data from here onward is used (held-out test period)")
    parser.add_argument("--end", required=True)
    parser.add_argument("--interval", default="5m")
    parser.add_argument("--cost-bps", type=float, default=20.0,
                         help="cost in basis points charged on EACH position change - a full "
                              "buy-then-sell round trip pays this twice, not once")
    parser.add_argument("--dip-values", default="-0.003,-0.005,-0.008,-0.01,-0.015,-0.02")
    parser.add_argument("--profit-values", default="0.005,0.008,0.01,0.015,0.02")
    parser.add_argument("--stop-values", default="0.01,0.015,0.02,0.03")
    parser.add_argument("--min-trades", type=float, default=5,
                         help="skip combos averaging fewer than this many trades per ticker - too rare to mean anything")
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--out", default="results/param_sweep.csv")
    args = parser.parse_args()

    # Populate ALPACA_API_KEY / ALPACA_SECRET_KEY from .env, if present -
    # needed now that crypto tickers may pull real historical bars from
    # Alpaca (see get_price_data_smart()), not just Yahoo Finance.
    load_dotenv()

    # Parse each comma-separated string flag into a list of actual floats,
    # e.g. "-0.003,-0.005" -> [-0.003, -0.005].
    dip_values = [float(x) for x in args.dip_values.split(",")]
    profit_values = [float(x) for x in args.profit_values.split(",")]
    stop_values = [float(x) for x in args.stop_values.split(",")]

    print(f"Loading data for {len(args.ticker)} tickers...")
    test_dfs = {}
    for ticker in args.ticker:
        raw, is_synthetic, source = get_price_data_smart(ticker, args.start, args.end, interval=args.interval)
        if is_synthetic:
            # Never let a parameter search draw conclusions from fake
            # data - drop any ticker neither Alpaca nor Yahoo could serve.
            print(f"  {ticker}: SKIPPED (only synthetic fallback data available - no real network access)")
            continue
        df = add_features(raw)
        # Only the held-out test period (on/after --split) is used here -
        # this script is meant to be run against a period you're willing
        # to treat as "unseen," not the same data a model might have
        # trained on.
        test_df = df[df.index >= args.split]
        if len(test_df) < 50:
            print(f"  {ticker}: SKIPPED (not enough test-period rows; widen --start/--split/--end)")
            continue
        test_dfs[ticker] = test_df
        print(f"  {ticker}: {len(test_df)} test-period rows ({source})")

    if not test_dfs:
        # Every single ticker failed to produce usable data - nothing to sweep.
        raise SystemExit("\nNo usable ticker data - this needs real network access to Yahoo Finance.")

    # How many bars occur per year at this --interval, so the avg_sharpe
    # column is annualized correctly - 252 for daily bars, or the 24/7
    # bars-per-year figure for anything intraday (this script mostly runs
    # against 5-minute crypto data, which is drastically different from 252).
    periods_per_year = 252 if args.interval == "1d" else PERIODS_PER_YEAR_24_7.get(args.interval, 252)

    # Every possible (dip, profit, stop) triple from the three value lists -
    # this is the actual "grid" the grid search tests exhaustively.
    combos = list(itertools.product(dip_values, profit_values, stop_values))
    print(f"\nSweeping {len(combos)} parameter combinations across {len(test_dfs)} tickers "
          f"({len(combos) * len(test_dfs)} backtests)...\n")

    # Evaluate every combination, keeping only the ones that passed the
    # --min-trades filter (evaluate_combo returns None for the rest).
    # The walrus operator (:=) assigns the result to r inline so it can
    # both be tested for "is not None" and used in the list comprehension
    # without calling evaluate_combo twice.
    rows = [r for dip, profit, stop in combos
            if (r := evaluate_combo(test_dfs, dip, profit, stop, args.cost_bps, args.min_trades, periods_per_year)) is not None]

    if not rows:
        raise SystemExit("No combination met --min-trades; lower it or widen the parameter ranges.")

    # Sort every surviving combination best-average-return first, and
    # save the whole grid to disk for later inspection (checking whether
    # the winner has healthy neighbors, per the module docstring above).
    results_df = pd.DataFrame(rows).sort_values("avg_total_return", ascending=False)
    results_df.to_csv(args.out, index=False)

    print(f"{'Dip':>8}{'Profit':>8}{'Stop':>8}{'AvgRet':>10}{'AvgSharpe':>11}{'AvgTrades':>11}{'WorstTicker':>13}")
    for _, row in results_df.head(args.top).iterrows():
        print(
            f"{row['dip_threshold']:>7.1%} {row['profit_target']:>7.1%} {row['stop_loss']:>7.1%} "
            f"{row['avg_total_return']:>9.1%} {row['avg_sharpe']:>11.2f} {row['avg_trades']:>11.1f} "
            f"{row['worst_ticker_return']:>12.1%}"
        )

    # The single best row by average return, called out explicitly below
    # the ranked table.
    best = results_df.iloc[0]
    print(
        f"\nBest average combo: dip={best['dip_threshold']:.1%} profit={best['profit_target']:.1%} "
        f"stop={best['stop_loss']:.1%}  (avg return {best['avg_total_return']:.1%} across {len(test_dfs)} tickers, "
        f"worst single ticker {best['worst_ticker_return']:.1%})"
    )
    print(f"Full grid ({len(rows)} combos) saved to {args.out}")
    print(
        "\nIMPORTANT - check for overfitting before trusting this: open the CSV, sort by "
        "dip_threshold/profit_target/stop_loss, and look at rows NEAR the winner. If nearby values "
        "also perform reasonably well, that's a real signal. If the winner is an isolated spike "
        "surrounded by much worse neighbors, that's almost always noise from testing many "
        "combinations, not a real edge. Either way, re-validate the winner on a DIFFERENT, later "
        "time window before trusting it with anything beyond fake money."
    )


if __name__ == "__main__":
    main()
