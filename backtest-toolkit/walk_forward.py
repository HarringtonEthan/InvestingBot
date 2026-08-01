"""
Walk-forward validation for any of the three rule-based/ML strategies in
src/strategies.py:
  --strategy day_trading  (dip / profit-target / stop-loss shape)
  --strategy rule_based   (dip / recovery-exit shape)
  --strategy ml_filtered  (same dip/recovery rule, gated by an
                           already-trained model's confidence; loads
                           --model-path rather than training a fresh
                           model just for this validation run)

A single backtest on ONE held-out test period can look great purely by
luck (the window happened to have a few dips that bounced). This script
instead splits the full --start/--end range into several SEQUENTIAL,
NON-OVERLAPPING windows and re-evaluates the exact same fixed parameter
combination independently on each one, so "does this actually hold up
over time, or did it just get lucky once" has a real answer instead of
a guess.

Read-only research tool - it doesn't place any trades.

Data source: any ticker requested at an intraday interval pulls historical
bars from Yahoo Finance by default. If you've set ALPACA_API_KEY /
ALPACA_SECRET_KEY in your .env (optional - a free Alpaca paper account
is enough), intraday requests try Alpaca first, which isn't subject to
Yahoo's ~60-day intraday history cap - useful for validating a strategy
over a longer real window than that. A daily interval (--interval 1d)
always goes straight to Yahoo, whose daily history is already decades
deep.
"""

from __future__ import annotations

import argparse

import pandas as pd
from dotenv import load_dotenv

from src.backtest import run_backtest
from src.data import get_price_data_smart, periods_per_year
from src.features import add_features
from src.symbols import resolve_symbol
from src.strategies import position_for_params
from src.model_store import load_model


def make_windows(start: str, end: str, n_windows: int) -> list[tuple[str, str]]:
    """
    Splits [start, end] into n_windows equal-length, sequential,
    non-overlapping (start, end) date-string pairs. Evenly spaced by
    calendar time, not by number of trading bars.
    """
    if n_windows < 1:
        raise ValueError("n_windows must be at least 1")
    edges = pd.date_range(start=start, end=end, periods=n_windows + 1)
    return [(edges[i].date().isoformat(), edges[i + 1].date().isoformat()) for i in range(n_windows)]


def evaluate_window(ticker: str, window_start: str, window_end: str, strategy: str, params: dict, args, model=None, threshold: float | None = None):
    """
    Runs one ticker's backtest over one window. Returns (BacktestResult,
    source) - source is "alpaca", "yahoo", or "synthetic" - or None if
    this window should be skipped entirely (no real data, or too few bars
    to mean anything).
    """
    raw, is_synthetic, source = get_price_data_smart(ticker, window_start, window_end, interval=args.interval)
    if is_synthetic:
        # Never let a validation run draw conclusions from fake data.
        return None
    df = add_features(raw)
    if len(df) < 50:
        return None
    position = position_for_params(strategy, df, params, model=model, threshold=threshold)
    ppy = periods_per_year(args.interval, is_crypto=resolve_symbol(ticker).is_crypto)
    result = run_backtest(df["Close"], position, cost_bps=args.cost_bps, periods_per_year=ppy)
    return result, source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", nargs="+", required=True, help="e.g. --ticker BTC-USD ETH-USD SOL-USD")
    parser.add_argument("--strategy", choices=["day_trading", "rule_based", "ml_filtered"], default="day_trading")
    parser.add_argument("--model-path", default="models/stock_model.pkl",
                         help="--strategy ml_filtered only")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--windows", type=int, default=4,
                         help="how many sequential, non-overlapping windows to split --start/--end into")
    parser.add_argument("--interval", default="5m",
                         help="bar size, e.g. 5m or 1d - don't leave this at 5m for a multi-year "
                              "--strategy rule_based validation, Yahoo's 5-minute history only "
                              "goes back about 60 days regardless of ticker")
    parser.add_argument("--cost-bps", type=float, default=20.0,
                         help="cost in basis points charged on EACH position change; crypto fees "
                              "run higher than stocks, so don't leave this at a stock-sized default")
    parser.add_argument("--dip-threshold", type=float, default=-0.04)
    parser.add_argument("--profit-target", type=float, default=0.01, help="--strategy day_trading only")
    parser.add_argument("--stop-loss", type=float, default=0.05, help="--strategy day_trading only")
    parser.add_argument("--exit-threshold", type=float, default=0.0,
                         help="--strategy rule_based only")
    parser.add_argument("--rule-stop-loss", type=float, default=None,
                         help="--strategy rule_based only, optional - a hard stop-loss (fraction "
                              "below entry price). Omit to validate without one.")
    parser.add_argument("--rule-stop-cooldown", type=int, default=None,
                         help="--strategy rule_based only, optional (needs --rule-stop-loss too) - "
                              "how many bars to wait before re-buying after a stop-loss exit. Without "
                              "this, a stop-loss can immediately re-trigger during a sustained "
                              "decline instead of actually protecting capital.")
    parser.add_argument("--out", default="results/walk_forward/walk_forward.csv")
    args = parser.parse_args()

    load_dotenv()

    model, threshold = None, None
    if args.strategy == "day_trading":
        params = {"dip_threshold": args.dip_threshold, "profit_target": args.profit_target, "stop_loss": args.stop_loss}
        params_desc = f"dip={args.dip_threshold:.1%} profit={args.profit_target:.1%} stop={args.stop_loss:.1%}"
    elif args.strategy == "rule_based":
        params = {"dip_threshold": args.dip_threshold, "exit_threshold": args.exit_threshold}
        params_desc = f"dip={args.dip_threshold:.1%} exit={args.exit_threshold:.1%}"
        if args.rule_stop_loss is not None:
            params["stop_loss"] = args.rule_stop_loss
            params_desc += f" stop={args.rule_stop_loss:.1%}"
            if args.rule_stop_cooldown is not None:
                params["stop_cooldown_bars"] = args.rule_stop_cooldown
                params_desc += f" cooldown={args.rule_stop_cooldown} bars"
    else:  # ml_filtered
        params = {"dip_threshold": args.dip_threshold, "exit_threshold": args.exit_threshold}
        params_desc = f"dip={args.dip_threshold:.1%} exit={args.exit_threshold:.1%}"
        loaded = load_model(args.model_path)
        if loaded is None:
            raise SystemExit(
                f"No saved model at {args.model_path!r} - train one first "
                f"(or point --model-path at an existing one)."
            )
        model, threshold, meta = loaded
        params_desc += f" (model trained {meta.get('trained_at', '?')}, threshold={threshold:.3f})"

    windows = make_windows(args.start, args.end, args.windows)

    print(f"Walk-forward: {args.windows} sequential windows across {args.start} -> {args.end}, "
          f"strategy={args.strategy} {params_desc}\n")

    all_rows = []

    for ticker in args.ticker:
        print(f"=== {ticker} ===")
        print(f"{'Window':<24}{'Return':>10}{'Sharpe':>10}{'MaxDD':>10}{'Trades':>9}  Source")
        window_returns = []
        for w_start, w_end in windows:
            label = f"{w_start} -> {w_end}"
            outcome = evaluate_window(ticker, w_start, w_end, args.strategy, params, args, model=model, threshold=threshold)
            if outcome is None:
                print(f"{label:<24}{'SKIPPED (no real data / window too short)':>39}")
                all_rows.append({
                    "ticker": ticker, "window_start": w_start, "window_end": w_end, "strategy": args.strategy,
                    **params, "source": "skipped", "total_return": "",
                    "sharpe": "", "max_drawdown": "", "trades": "",
                })
                continue
            result, source = outcome
            window_returns.append((result.total_return, result.num_trades))
            print(
                f"{label:<24}{result.total_return:>9.1%} {result.sharpe:>10.2f} "
                f"{result.max_drawdown:>9.1%} {result.num_trades:>9}  {source}"
            )
            all_rows.append({
                "ticker": ticker, "window_start": w_start, "window_end": w_end, "strategy": args.strategy,
                **params, "source": source,
                "total_return": result.total_return, "sharpe": result.sharpe,
                "max_drawdown": result.max_drawdown, "trades": result.num_trades,
            })

        if len(window_returns) < 2:
            print("Not enough usable windows to assess consistency - widen --start/--end, "
                  "use a coarser --interval, or reduce --windows.\n")
            continue

        returns = pd.Series([r for r, _ in window_returns])
        untraded = sum(1 for _, trades in window_returns if trades == 0)
        losing = int((returns < 0).sum())
        print(
            f"\nAcross {len(returns)} usable windows: avg return {returns.mean():.1%}, "
            f"worst window {returns.min():.1%}, std dev {returns.std():.1%}"
        )
        if untraded:
            print(f"NOTE: {untraded}/{len(returns)} windows never traded at all - "
                  f"their 0.0% return reflects an untested window, not a proven-safe one.")
        if losing:
            print(f"WARNING: {losing}/{len(returns)} windows were net losers - this combination "
                  f"does not hold up consistently across time, not just on a single favorable period.")
        print()

    pd.DataFrame(all_rows).to_csv(args.out, index=False)
    print(f"Full per-window results saved to {args.out}")


if __name__ == "__main__":
    main()
