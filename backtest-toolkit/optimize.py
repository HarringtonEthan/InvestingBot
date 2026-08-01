"""
Systematic parameter search across multiple tickers at once, for any of
the three strategies in src/strategies.py:
  --strategy day_trading  (dip / profit-target / stop-loss shape)
  --strategy rule_based   (dip / recovery-exit shape; --stop-loss-values
                           optionally adds a hard downside cap here too)
  --strategy ml_filtered  (same dip/recovery rule, gated by an
                           already-trained model's confidence; loads
                           --model-path rather than training a fresh
                           model just for this search)

This exists because hand-picking one threshold combination and hoping
it's good is exactly the overfitting trap this toolkit is built to help
you avoid. Instead of chasing "the highest backtest number," this:

  - Tests every combination across ALL tickers you give it and reports
    the AVERAGE, not the best single ticker (a combo that only works on
    one ticker isn't a real edge, it's luck).
  - Skips combos that trade too rarely to mean anything (--min-trades).
  - Writes the full grid to CSV so you can check whether a good result
    sits among other similarly-good neighboring settings (a real signal)
    or is an isolated spike surrounded by bad neighbors (almost always
    noise from testing many combinations, not a real edge).

Still not a substitute for testing the winner on a further, later,
held-out time window before trusting it with anything beyond fake money -
this script tells you what looked best on the period you gave it, not
what will keep working going forward. See walk_forward.py for that next
step.

Data source: any ticker at an intraday interval pulls historical bars
from Yahoo Finance by default, or from Alpaca first if you've set
ALPACA_API_KEY/ALPACA_SECRET_KEY in your .env (optional - lifts Yahoo's
~60-day intraday history cap). Daily bars (--interval 1d) always go
straight to Yahoo, whose daily history is already decades deep.
"""

from __future__ import annotations

import argparse
import itertools

import pandas as pd
from dotenv import load_dotenv

from src.backtest import run_backtest
from src.data import get_price_data_smart, periods_per_year
from src.features import add_features
from src.strategies import position_for_params
from src.model_store import load_model
from src.symbols import resolve_symbol


def evaluate_combo(strategy: str, test_dfs: dict, params: dict, cost_bps: float, min_trades: float, interval: str, model=None, threshold: float | None = None):
    """
    Backtests one parameter combination against every ticker in test_dfs
    and averages the results - a single ticker's number never gets
    reported on its own, only ever as part of this cross-ticker average.
    Returns None if the combo trades too rarely across the whole set to
    be filtered out by --min-trades before it ever reaches the results
    table.
    """
    returns, sharpes, trades = [], [], []
    for ticker, test_df in test_dfs.items():
        position = position_for_params(strategy, test_df, params, model=model, threshold=threshold)
        ppy = periods_per_year(interval, is_crypto=resolve_symbol(ticker).is_crypto)
        result = run_backtest(test_df["Close"], position, cost_bps=cost_bps, periods_per_year=ppy)
        returns.append(result.total_return)
        if result.sharpe == result.sharpe:  # skip NaN (zero-trade combos)
            sharpes.append(result.sharpe)
        trades.append(result.num_trades)

    avg_trades = sum(trades) / len(trades)
    if avg_trades < min_trades:
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
    parser.add_argument("--strategy", choices=["day_trading", "rule_based", "ml_filtered"], default="day_trading")
    parser.add_argument("--model-path", default="models/stock_model.pkl",
                         help="--strategy ml_filtered only")
    parser.add_argument("--start", required=True)
    parser.add_argument("--split", required=True, help="only data from here onward is used (held-out test period)")
    parser.add_argument("--end", required=True)
    parser.add_argument("--interval", default="5m",
                         help="bar size, e.g. 5m or 1d - don't leave this at 5m for a multi-year "
                              "--strategy rule_based search, Yahoo's 5-minute history only goes "
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
                         help="--strategy rule_based only")
    parser.add_argument("--stop-loss-values", default=None,
                         help="--strategy rule_based only, optional - a hard stop-loss (fraction "
                              "below entry price) to sweep alongside dip/exit, e.g. 0.03,0.05. "
                              "Omit entirely to search without one.")
    parser.add_argument("--stop-cooldown-values", default=None,
                         help="--strategy rule_based only, optional (needs --stop-loss-values too) - "
                              "how many bars to wait before re-buying after a stop-loss exit, swept "
                              "alongside dip/exit/stop, e.g. 5,10,20. Without this, a stop-loss can "
                              "immediately re-trigger during a sustained decline instead of actually "
                              "protecting capital - a real validation run found one ticker/window go "
                              "from -3.2%% with no stop-loss to -27.4%% with a stop but no cooldown.")
    parser.add_argument("--min-trades", type=float, default=5,
                         help="skip combos averaging fewer than this many trades per ticker - too rare to mean anything")
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--out", default="results/param_sweep/param_sweep.csv")
    args = parser.parse_args()

    load_dotenv()

    dip_values = [float(x) for x in args.dip_values.split(",")]

    print(f"Loading data for {len(args.ticker)} tickers...")
    test_dfs = {}
    for ticker in args.ticker:
        raw, is_synthetic, source = get_price_data_smart(ticker, args.start, args.end, interval=args.interval)
        if is_synthetic:
            print(f"  {ticker}: SKIPPED (only synthetic fallback data available - no real network access)")
            continue
        df = add_features(raw)
        test_df = df[df.index >= args.split]
        if len(test_df) < 50:
            print(f"  {ticker}: SKIPPED (not enough test-period rows; widen --start/--split/--end)")
            continue
        test_dfs[ticker] = test_df
        print(f"  {ticker}: {len(test_df)} test-period rows ({source})")

    if not test_dfs:
        raise SystemExit("\nNo usable ticker data - this needs real network access to Yahoo Finance.")

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
        exit_values = [float(x) for x in args.exit_values.split(",")]
        combos = [
            {"dip_threshold": dip, "exit_threshold": exit_}
            for dip, exit_ in itertools.product(dip_values, exit_values)
        ]
        loaded = load_model(args.model_path)
        if loaded is None:
            raise SystemExit(
                f"No saved model at {args.model_path!r} - train one first "
                f"(or point --model-path at an existing one)."
            )
        model, threshold, meta = loaded
        print(f"Loaded model from {args.model_path} (trained {meta.get('trained_at', '?')}, "
              f"threshold={threshold:.3f})\n")

    print(f"\nSweeping {len(combos)} parameter combinations across {len(test_dfs)} tickers "
          f"({len(combos) * len(test_dfs)} backtests)...\n")

    rows = [r for params in combos
            if (r := evaluate_combo(args.strategy, test_dfs, params, args.cost_bps, args.min_trades, args.interval, model=model, threshold=threshold)) is not None]

    if not rows:
        raise SystemExit("No combination met --min-trades; lower it or widen the parameter ranges.")

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
        "time window (walk_forward.py) before trusting it with anything beyond fake money."
    )


if __name__ == "__main__":
    main()
