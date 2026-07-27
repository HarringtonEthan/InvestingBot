"""
Walk-forward validation for the day-trading (dip buy / profit target /
stop loss) strategy - the one actually running live on crypto.

Every other backtest tool in this repo (`main.py`, `optimize.py`) scores
a strategy on ONE held-out test period. A combination that looks great on
that single window can still just be luck - the window happened to have a
few dips that bounced. This script instead splits the full --start/--end
range into several SEQUENTIAL, NON-OVERLAPPING windows and re-evaluates
the exact same fixed parameter combination independently on each one, so
"does this actually hold up over time, or did it just get lucky once" has
a real answer instead of a guess. This is the "multiple distinct,
non-overlapping time periods" validation named as a 1.0.0 requirement in
CHANGELOG.md.

Read-only research tool - it doesn't change what the live crypto bot
does. Defaults match the parameters the live crypto workflow actually
runs with, so running this with no threshold flags evaluates the
strategy currently trading real (paper) money.

Caveat: Yahoo Finance only keeps a limited window of intraday history
(roughly 60 days for 5-minute bars). Walk-forwarding at --interval 5m
over a long --start/--end range will just produce early windows that
fall back to synthetic data (and get skipped) or fail outright - use a
recent --start, or a coarser --interval (1h, 1d) to validate over a
longer stretch of calendar time.
"""

# Lets type hints work without issue in this Python version.
from __future__ import annotations

# argparse for command-line flags.
import argparse

# pandas for date_range (splitting the overall range into windows) and
# Series (computing mean/std/min across each window's result).
import pandas as pd

# The backtest engine used to score every window.
from src.backtest import run_backtest
# Price data loading; also the bars-per-year table for intraday
# intervals, reused so each window's Sharpe is annualized correctly.
from src.data import PERIODS_PER_YEAR_24_7, get_price_data
# Technical indicator computation.
from src.features import add_features
# The strategy actually running live on crypto.
from src.strategies import dip_buy_profit_target


def make_windows(start: str, end: str, n_windows: int) -> list[tuple[str, str]]:
    """
    Splits [start, end] into n_windows equal-length, sequential,
    non-overlapping (start, end) date-string pairs. Evenly spaced by
    calendar time, not by number of trading bars - a window over a
    weekend-heavy stretch will have fewer stock bars than one that isn't,
    which is fine since each window is still scored independently.
    """
    if n_windows < 1:
        raise ValueError("n_windows must be at least 1")
    # n_windows windows need n_windows + 1 boundary dates (start, ...,
    # end), evenly spaced across the full range.
    edges = pd.date_range(start=start, end=end, periods=n_windows + 1)
    return [(edges[i].date().isoformat(), edges[i + 1].date().isoformat()) for i in range(n_windows)]


def evaluate_window(ticker: str, window_start: str, window_end: str, args, periods_per_year: float):
    """Runs one ticker's backtest over one window. Returns a BacktestResult, or None if skipped."""
    raw, is_synthetic = get_price_data(ticker, window_start, window_end, interval=args.interval)
    if is_synthetic:
        # Never let a validation run draw conclusions from fake data -
        # a window with no real data available is reported as skipped,
        # not silently scored on invented prices.
        return None
    df = add_features(raw)
    if len(df) < 50:
        # Not enough bars in this window for pct_below_sma20 (needs 20
        # bars to warm up) plus a meaningful number of trading bars after
        # that - too short a window to mean anything.
        return None
    position = dip_buy_profit_target(
        df, dip_threshold=args.dip_threshold, profit_target=args.profit_target, stop_loss=args.stop_loss,
    )
    return run_backtest(df["Close"], position, cost_bps=args.cost_bps, periods_per_year=periods_per_year)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", nargs="+", required=True, help="e.g. --ticker BTC-USD ETH-USD SOL-USD")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--windows", type=int, default=4,
                         help="how many sequential, non-overlapping windows to split --start/--end into")
    parser.add_argument("--interval", default="5m", help="matches the live crypto schedule by default")
    parser.add_argument("--cost-bps", type=float, default=20.0,
                         help="cost in basis points charged on EACH position change; crypto fees "
                              "run higher than stocks, so don't leave this at a stock-sized default")
    # Defaults intentionally match the parameters .github/workflows/paper-trade-crypto.yml
    # actually runs live with, so `python walk_forward.py --ticker ... --start ... --end ...`
    # with no threshold flags validates the exact strategy currently trading paper money.
    parser.add_argument("--dip-threshold", type=float, default=-0.01)
    parser.add_argument("--profit-target", type=float, default=0.01)
    parser.add_argument("--stop-loss", type=float, default=0.03)
    args = parser.parse_args()

    periods_per_year = 252 if args.interval == "1d" else PERIODS_PER_YEAR_24_7.get(args.interval, 252)
    windows = make_windows(args.start, args.end, args.windows)

    print(
        f"Walk-forward: {args.windows} sequential windows across {args.start} -> {args.end}, "
        f"dip={args.dip_threshold:.1%} profit={args.profit_target:.1%} stop={args.stop_loss:.1%}\n"
    )

    for ticker in args.ticker:
        print(f"=== {ticker} ===")
        print(f"{'Window':<24}{'Return':>10}{'Sharpe':>10}{'MaxDD':>10}{'Trades':>9}")
        # Collected only from windows that actually produced a result -
        # a skipped window (no real data / too short) contributes nothing
        # to the consistency check below rather than counting as a zero.
        window_returns = []
        for w_start, w_end in windows:
            label = f"{w_start} -> {w_end}"
            result = evaluate_window(ticker, w_start, w_end, args, periods_per_year)
            if result is None:
                print(f"{label:<24}{'SKIPPED (no real data / window too short)':>39}")
                continue
            window_returns.append((result.total_return, result.num_trades))
            print(
                f"{label:<24}{result.total_return:>9.1%} {result.sharpe:>10.2f} "
                f"{result.max_drawdown:>9.1%} {result.num_trades:>9}"
            )

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


if __name__ == "__main__":
    main()
