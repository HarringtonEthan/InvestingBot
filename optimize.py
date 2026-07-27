"""
Systematic parameter search across multiple tickers at once, for any of
the three rule-based/ML strategies this project runs live:
  --strategy day_trading  (crypto's strategy - dip / profit-target / stop-loss)
  --strategy rule_based   (stocks' underlying strategy - dip / recovery-exit;
                           --stop-loss-values optionally adds a hard downside
                           cap here too, the same shape day_trading always has)
  --strategy ml_filtered  (stocks' ML-gated variant - same dip/recovery rule,
                           but a dip is only acted on if an already-trained
                           model's predicted bounce-probability clears its
                           calibrated threshold; loads --model-path (default
                           models/stock_model.pkl) rather than training a
                           fresh model just for this search, so this tests
                           the exact model live_trade.py would actually use)

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

Data source: any ticker at an intraday interval pulls historical bars from
Alpaca first (see src/data.py's get_price_data_smart()) - crypto and
stocks alike - since Yahoo Finance's ~60-day intraday history window
would otherwise cap any real grid search at a couple months. Needs
ALPACA_API_KEY/ALPACA_SECRET_KEY in your .env, same as live trading, even
though this never places an order. Stock tickers on daily bars (--interval
1d) don't need this - Yahoo's daily history is already decades deep, no
cap to work around.
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
# The shared "which strategy takes which parameters" dispatch, also used
# by walk_forward.py - keeps the two scripts from each maintaining their
# own copy of this mapping.
from src.strategies import position_for_params
# Loading an already-trained, already-saved model for --strategy
# ml_filtered - the exact model live_trade.py would use, not a fresh one
# trained just for this search.
from src.model_store import load_model


def evaluate_combo(strategy: str, test_dfs: dict, params: dict, cost_bps: float, min_trades: float, periods_per_year: float, model=None, threshold: float | None = None):
    """
    Backtests one parameter combination (its shape depends on `strategy`
    - see _position_for()) against every ticker in test_dfs and averages
    the results - a single ticker's number never gets reported on its
    own, only ever as part of this cross-ticker average (see the module
    docstring on why). Returns None if the combo trades too rarely
    across the whole set to be filtered out by --min-trades before it
    ever reaches the results table. `model`/`threshold` are only used
    for --strategy ml_filtered - see position_for_params().
    """
    returns, sharpes, trades = [], [], []
    for test_df in test_dfs.values():
        # Run this one parameter combination against every ticker's data.
        position = position_for_params(strategy, test_df, params, model=model, threshold=threshold)
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
        **params,
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
    parser.add_argument("--strategy", choices=["day_trading", "rule_based", "ml_filtered"], default="day_trading",
                         help="day_trading = crypto's dip/profit-target/stop-loss shape (default); "
                              "rule_based = stocks' dip/recovery-exit shape; ml_filtered = the same "
                              "rule, gated by an already-trained model's confidence (see --model-path)")
    parser.add_argument("--model-path", default="models/stock_model.pkl",
                         help="--strategy ml_filtered only - loads an already-trained model+threshold "
                              "(see train_stock_model.py) rather than training a fresh one just for "
                              "this search, so the search tests the exact model live_trade.py would "
                              "actually use")
    parser.add_argument("--start", required=True)
    parser.add_argument("--split", required=True, help="only data from here onward is used (held-out test period)")
    parser.add_argument("--end", required=True)
    parser.add_argument("--interval", default="5m",
                         help="bar size, e.g. 5m for crypto (the default - matches the live crypto "
                              "schedule) or 1d for stocks - don't leave this at 5m for a multi-year "
                              "--strategy rule_based stock search, Yahoo's 5-minute history only goes "
                              "back about 60 days regardless of ticker")
    parser.add_argument("--cost-bps", type=float, default=20.0,
                         help="cost in basis points charged on EACH position change - a full "
                              "buy-then-sell round trip pays this twice, not once")
    parser.add_argument("--dip-values", default="-0.003,-0.005,-0.008,-0.01,-0.015,-0.02")
    parser.add_argument("--profit-values", default="0.005,0.008,0.01,0.015,0.02",
                         help="--strategy day_trading only")
    parser.add_argument("--stop-values", default="0.01,0.015,0.02,0.03",
                         help="--strategy day_trading only")
    parser.add_argument("--exit-values", default="-0.01,0.0,0.01",
                         help="--strategy rule_based only - how far above/below the SMA counts as "
                              "'recovered enough to sell' (0.0 = back at the average)")
    parser.add_argument("--stop-loss-values", default=None,
                         help="--strategy rule_based only, optional - a hard stop-loss (fraction "
                              "below entry price) to sweep alongside dip/exit, e.g. 0.03,0.05 - the "
                              "same downside cap day_trading always has. Omit entirely to search "
                              "without one (the original mean-reversion-only behavior); rule_based "
                              "never had this until walk-forward runs on daily stock bars found "
                              "ticker/window drawdowns as deep as -40%% while waiting for a recovery.")
    parser.add_argument("--stop-cooldown-values", default=None,
                         help="--strategy rule_based only, optional (needs --stop-loss-values too) - "
                              "how many bars to wait before re-buying after a stop-loss exit, swept "
                              "alongside dip/exit/stop, e.g. 5,10,20. Without this, a stop-loss can "
                              "immediately re-trigger during a sustained decline - buy, stop out, buy "
                              "again since the dip never went away, stop out again - turning one long "
                              "unrealized drawdown into several smaller realized losses plus extra "
                              "transaction costs instead of actually protecting capital. Found running "
                              "a real walk-forward validation with a stop-loss but no cooldown: SPY's "
                              "2019-2021 window went from -3.2%% with no stop-loss to -27.4%% with one. "
                              "Omit to search without a cooldown (0 bars).")
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

    # Build the actual parameter grid - shape depends on --strategy, since
    # these three strategies don't all take the same parameters.
    model, threshold = None, None
    if args.strategy == "day_trading":
        profit_values = [float(x) for x in args.profit_values.split(",")]
        stop_values = [float(x) for x in args.stop_values.split(",")]
        combos = [
            {"dip_threshold": dip, "profit_target": profit, "stop_loss": stop}
            for dip, profit, stop in itertools.product(dip_values, profit_values, stop_values)
        ]
    elif args.strategy == "rule_based":
        exit_values = [float(x) for x in args.exit_values.split(",")]
        if args.stop_loss_values:
            stop_loss_values = [float(x) for x in args.stop_loss_values.split(",")]
            if args.stop_cooldown_values:
                cooldown_values = [int(x) for x in args.stop_cooldown_values.split(",")]
                combos = [
                    {"dip_threshold": dip, "exit_threshold": exit_, "stop_loss": stop, "stop_cooldown_bars": cd}
                    for dip, exit_, stop, cd in itertools.product(dip_values, exit_values, stop_loss_values, cooldown_values)
                ]
            else:
                combos = [
                    {"dip_threshold": dip, "exit_threshold": exit_, "stop_loss": stop}
                    for dip, exit_, stop in itertools.product(dip_values, exit_values, stop_loss_values)
                ]
        else:
            combos = [
                {"dip_threshold": dip, "exit_threshold": exit_}
                for dip, exit_ in itertools.product(dip_values, exit_values)
            ]
    else:  # ml_filtered
        # No stop-loss/cooldown here - ml_filtered_dip_buy doesn't support
        # them (matches live_trade.py's actual ml_filtered strategy shape).
        exit_values = [float(x) for x in args.exit_values.split(",")]
        combos = [
            {"dip_threshold": dip, "exit_threshold": exit_}
            for dip, exit_ in itertools.product(dip_values, exit_values)
        ]
        loaded = load_model(args.model_path)
        if loaded is None:
            raise SystemExit(
                f"No saved model at {args.model_path!r} - run train_stock_model.py first "
                f"(or point --model-path at an existing one)."
            )
        model, threshold, meta = loaded
        print(f"Loaded model from {args.model_path} (trained {meta.get('trained_at', '?')}, "
              f"threshold={threshold:.3f})\n")

    print(f"\nSweeping {len(combos)} parameter combinations across {len(test_dfs)} tickers "
          f"({len(combos) * len(test_dfs)} backtests)...\n")

    # Evaluate every combination, keeping only the ones that passed the
    # --min-trades filter (evaluate_combo returns None for the rest).
    # The walrus operator (:=) assigns the result to r inline so it can
    # both be tested for "is not None" and used in the list comprehension
    # without calling evaluate_combo twice.
    rows = [r for params in combos
            if (r := evaluate_combo(args.strategy, test_dfs, params, args.cost_bps, args.min_trades, periods_per_year, model=model, threshold=threshold)) is not None]

    if not rows:
        raise SystemExit("No combination met --min-trades; lower it or widen the parameter ranges.")

    # Sort every surviving combination best-average-return first, and
    # save the whole grid to disk for later inspection (checking whether
    # the winner has healthy neighbors, per the module docstring above).
    results_df = pd.DataFrame(rows).sort_values("avg_total_return", ascending=False)
    results_df.to_csv(args.out, index=False)

    if args.strategy == "day_trading":
        print(f"{'Dip':>8}{'Profit':>8}{'Stop':>8}{'AvgRet':>10}{'AvgSharpe':>11}{'AvgTrades':>11}{'WorstTicker':>13}")
        for _, row in results_df.head(args.top).iterrows():
            print(
                f"{row['dip_threshold']:>7.1%} {row['profit_target']:>7.1%} {row['stop_loss']:>7.1%} "
                f"{row['avg_total_return']:>9.1%} {row['avg_sharpe']:>11.2f} {row['avg_trades']:>11.1f} "
                f"{row['worst_ticker_return']:>12.1%}"
            )
    else:  # rule_based or ml_filtered
        has_stop = "stop_loss" in results_df.columns
        has_cooldown = "stop_cooldown_bars" in results_df.columns
        stop_header = f"{'Stop':>8}" if has_stop else ""
        cooldown_header = f"{'Cooldown':>10}" if has_cooldown else ""
        print(
            f"{'Dip':>8}{'Exit':>8}{stop_header}{cooldown_header}"
            f"{'AvgRet':>10}{'AvgSharpe':>11}{'AvgTrades':>11}{'WorstTicker':>13}"
        )
        for _, row in results_df.head(args.top).iterrows():
            stop_col = f"{row['stop_loss']:>7.1%} " if has_stop else ""
            cooldown_col = f"{row['stop_cooldown_bars']:>9.0f} " if has_cooldown else ""
            print(
                f"{row['dip_threshold']:>7.1%} {row['exit_threshold']:>7.1%} {stop_col}{cooldown_col}"
                f"{row['avg_total_return']:>9.1%} {row['avg_sharpe']:>11.2f} {row['avg_trades']:>11.1f} "
                f"{row['worst_ticker_return']:>12.1%}"
            )

    # The single best row by average return, called out explicitly below
    # the ranked table.
    best = results_df.iloc[0]
    if args.strategy == "day_trading":
        best_desc = f"dip={best['dip_threshold']:.1%} profit={best['profit_target']:.1%} stop={best['stop_loss']:.1%}"
    else:
        best_desc = f"dip={best['dip_threshold']:.1%} exit={best['exit_threshold']:.1%}"
        if "stop_loss" in results_df.columns:
            best_desc += f" stop={best['stop_loss']:.1%}"
        if "stop_cooldown_bars" in results_df.columns:
            best_desc += f" cooldown={best['stop_cooldown_bars']:.0f} bars"
    print(
        f"\nBest average combo: {best_desc}  (avg return {best['avg_total_return']:.1%} across "
        f"{len(test_dfs)} tickers, worst single ticker {best['worst_ticker_return']:.1%})"
    )
    print(f"Full grid ({len(rows)} combos) saved to {args.out}")
    print(
        "\nIMPORTANT - check for overfitting before trusting this: open the CSV, sort by "
        "the parameter columns, and look at rows NEAR the winner. If nearby values "
        "also perform reasonably well, that's a real signal. If the winner is an isolated spike "
        "surrounded by much worse neighbors, that's almost always noise from testing many "
        "combinations, not a real edge. Either way, re-validate the winner on a DIFFERENT, later "
        "time window before trusting it with anything beyond fake money."
    )


if __name__ == "__main__":
    main()
