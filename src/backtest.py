"""Simple long/cash backtest engine with transaction costs."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class BacktestResult:
    equity_curve: pd.Series
    total_return: float
    annualized_return: float
    annualized_vol: float
    sharpe: float
    max_drawdown: float
    num_trades: int


def run_backtest(
    close: pd.Series,
    target_position: pd.Series,
    initial_capital: float = 10_000.0,
    cost_bps: float = 5.0,
) -> BacktestResult:
    """
    target_position[t] is the desired fraction of capital in the asset
    based on information known at the close of day t. The position is
    assumed executed at day t+1's close (no lookahead, one day of
    execution lag), and each change in position incurs `cost_bps` basis
    points of the traded notional as a simple slippage/fee model.
    """
    close = close.reindex(target_position.index)
    executed_position = target_position.shift(1).fillna(0.0)

    daily_ret = close.pct_change().fillna(0.0)

    pos_change = executed_position.diff().abs().fillna(executed_position.abs())
    cost = pos_change * (cost_bps / 10_000.0)

    strategy_ret = executed_position * daily_ret - cost
    equity = initial_capital * (1 + strategy_ret).cumprod()

    total_return = equity.iloc[-1] / equity.iloc[0] - 1
    n_days = len(equity)
    years = n_days / 252
    annualized_return = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1 if years > 0 else np.nan

    vol = strategy_ret.std() * np.sqrt(252)
    sharpe = (strategy_ret.mean() * 252) / vol if vol > 0 else np.nan

    running_max = equity.cummax()
    drawdown = equity / running_max - 1
    max_dd = drawdown.min()

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
