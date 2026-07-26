"""Simple long/cash backtest engine with transaction costs."""

# Lets type hints work without issue in this Python version.
from __future__ import annotations

# dataclass is a shortcut for a small class that just holds a bunch of
# named result fields (BacktestResult below) without hand-writing __init__.
from dataclasses import dataclass

# numpy for math helpers (sqrt, nan); pandas for the Series types the
# backtest operates on (a price series in, an equity curve out).
import numpy as np
import pandas as pd


@dataclass
class BacktestResult:
    equity_curve: pd.Series     # simulated account value over time, day by day
    total_return: float          # overall % gain/loss from start to end
    annualized_return: float     # total_return converted to an equivalent "per year" rate
    annualized_vol: float        # how much the strategy's daily returns bounce around, scaled to a yearly figure
    sharpe: float                 # risk-adjusted return: annualized return divided by annualized volatility
    max_drawdown: float           # the worst peak-to-trough decline seen at any point in the run
    num_trades: int               # how many times the position size actually changed


def run_backtest(
    close: pd.Series,
    target_position: pd.Series,
    initial_capital: float = 10_000.0,
    cost_bps: float = 5.0,
    periods_per_year: float = 252,
) -> BacktestResult:
    """
    target_position[t] is the desired fraction of capital in the asset
    based on information known at the close of day t. The position is
    assumed executed at day t+1's close (no lookahead, one day of
    execution lag), and each change in position incurs `cost_bps` basis
    points of the traded notional as a simple slippage/fee model.

    `periods_per_year` controls the annualized-return/vol/Sharpe scaling
    and must match whatever bar size `close`/`target_position` actually
    use - 252 (the default) is correct for daily stock bars, but wrong
    for anything else: 5-minute crypto bars, for example, have ~105,120
    periods in a year, not 252. Passing the wrong value doesn't affect
    total_return or max_drawdown (those aren't annualized), only the
    annualized_return/annualized_vol/sharpe fields.
    """
    # Line up the price series to exactly the same dates as the strategy's
    # position series, in case they came in with different date ranges.
    close = close.reindex(target_position.index)
    # Shift the strategy's decisions forward by one bar (today's decision
    # takes effect starting tomorrow, not today) - this is what enforces
    # "no lookahead." fillna(0.0) means the very first bar (which has
    # nothing to shift from) starts out of the market.
    executed_position = target_position.shift(1).fillna(0.0)

    # Day-over-day % change in price; fillna(0.0) makes the first day's
    # undefined return (nothing to compare to) count as zero instead of NaN.
    daily_ret = close.pct_change().fillna(0.0)

    # How much the position size changed from the previous bar, as a
    # positive magnitude - diff() gives the signed change, abs() drops
    # the sign since a cost is a cost whether buying or selling.
    # fillna(executed_position.abs()) handles the very first bar: there's
    # no "previous" position to diff against, so treat entering (or not
    # entering) the position as the full change from zero.
    pos_change = executed_position.diff().abs().fillna(executed_position.abs())
    # Transaction cost model: cost_bps basis points (1 bp = 0.01%) of
    # however much the position changed that day.
    cost = pos_change * (cost_bps / 10_000.0)

    # The strategy's actual daily return: however much of the day's price
    # move it was exposed to (executed_position * daily_ret), minus
    # whatever it paid in costs that day.
    strategy_ret = executed_position * daily_ret - cost
    # Turn a series of daily % returns into an actual running account
    # value: (1 + return) compounded day over day, starting from
    # initial_capital.
    equity = initial_capital * (1 + strategy_ret).cumprod()

    # Overall return from the very first to the very last equity value.
    total_return = equity.iloc[-1] / equity.iloc[0] - 1
    n_bars = len(equity)
    years = n_bars / periods_per_year  # e.g. 252 trading days/year for daily bars
    # Convert the total return into an equivalent constant annual rate -
    # e.g. doubling your money over 2 years is a ~41%/year annualized
    # return, not 100%/year. Guarded against years <= 0 (degenerate case
    # of a near-empty backtest) to avoid a divide-by-zero/negative-power error.
    annualized_return = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1 if years > 0 else np.nan

    # Standard deviation of per-bar returns, scaled up to a yearly figure
    # by multiplying by sqrt(periods_per_year) - volatility scales with
    # the square root of time, not time itself.
    vol = strategy_ret.std() * np.sqrt(periods_per_year)
    # Sharpe ratio: annualized average return divided by annualized
    # volatility - a measure of return per unit of risk taken. Guarded
    # against vol == 0 (a strategy that never actually took a position,
    # for example) to avoid dividing by zero.
    sharpe = (strategy_ret.mean() * periods_per_year) / vol if vol > 0 else np.nan

    # Running peak equity value seen so far at each point in time.
    running_max = equity.cummax()
    # How far below that running peak the account currently sits, as a
    # fraction (negative or zero) - the classic "drawdown" measure.
    drawdown = equity / running_max - 1
    # The single worst (most negative) drawdown seen anywhere in the run.
    max_dd = drawdown.min()

    # Count how many days actually involved a position change (pos_change
    # > 0) - a rough trade count (each entry or exit counts as one "trade").
    num_trades = int((pos_change > 0).sum())

    return BacktestResult(
        equity_curve=equity,
        total_return=total_return,
        annualized_return=annualized_return,
        annualized_vol=vol,
        sharpe=sharpe,
        max_drawdown=max_dd,
        num_trades=num_trades,
    )
