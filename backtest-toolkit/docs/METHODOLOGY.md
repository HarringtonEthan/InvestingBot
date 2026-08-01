# Methodology notes

## No-lookahead guarantee

`src/backtest.py`'s `run_backtest()` shifts every position decision forward by exactly one bar before it's allowed to affect the simulated equity curve:

```python
executed_position = target_position.shift(1).fillna(0.0)
```

This means a decision made using bar `t`'s closing data can only take effect starting at bar `t+1` — it can never "trade on" information from the same bar it was computed from. This is enforced structurally in the engine itself, not just as a convention strategies are supposed to follow, so a strategy function can't accidentally violate it.

## Transaction costs

Every change in position pays `cost_bps` basis points of the traded notional:

```python
cost = pos_change * (cost_bps / 10_000.0)
```

A full round trip (buy then sell) pays this twice. The default of 5bps is reasonable for liquid stocks; crypto spreads and fees typically run higher (15-25bps is a more realistic starting point) — `optimize.py` and `walk_forward.py` both default to 20bps for exactly this reason.

## Overfitting checks

`optimize.py` scores every parameter combination by its **average** return across every ticker you give it, not the best single ticker — a combination that only works on one symbol isn't a real edge. It also reports the worst-performing ticker under each combination, so a combo that looks great on average but wrecks one ticker is visible, not averaged away.

`walk_forward.py` goes a step further: it splits your full date range into several sequential, non-overlapping windows and re-scores the *same fixed parameters* independently on each one. A real edge should show up as a positive (or at least not catastrophically negative) result across most windows. A parameter combination that only worked in one window — especially if neighboring parameter values in `optimize.py`'s grid performed much worse — is much more likely to be noise from testing many combinations than a real, repeatable edge.

## What this toolkit does not do

- It does not place trades or connect to a live brokerage by default — it's a research/backtesting tool.
- It does not guarantee any strategy is profitable. A careful backtest reduces the chance you're fooling yourself; it can't eliminate the gap between simulated and live results (slippage on real order execution, latency, liquidity at the moment you actually trade, and regime change are all real and none of them show up in a backtest).
- The included ML "dip filter" is a simple example (a shallow RandomForest with basic technical features) meant to demonstrate correct methodology (proper label construction, threshold calibration from training data only), not a production-grade predictive model.
