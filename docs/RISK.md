# Risk controls and real-money requirements

[← Back to README](../README.md)

## Risk controls currently in place

Two automated controls exist specifically to bound how much damage a bad
run (or a bad stretch of runs) can do, on top of the "paper trading only,
two locks required to go live" safeguard below:

- **`--max-notional`** caps the dollar amount of a single BUY. The live
  crypto workflow passes `--max-notional 2000`, so no single trade can
  exceed $2,000 regardless of how the even-split-across-tickers budget
  would otherwise size it (which can run well above that as the account
  grows). Passing `--max-notional 0` explicitly caps every buy at $0
  (never buy) rather than silently falling back to the uncapped split -
  see `CHANGELOG.md` 0.5.2 for why that distinction needed a dedicated
  fix.
- **`--daily-loss-limit`** (default 5%) is a circuit breaker: once the
  account is down 5%+ from that day's starting equity, new BUYs are
  blocked for the rest of the day. It never blocks SELLs - an existing
  position's own profit-target/stop-loss exit still runs normally, since
  blocking that would be the opposite of what a circuit breaker is for.

Both are starting points, not tuned values - see `docs/RESEARCH.md` for
how to validate parameter choices before changing them, and see
`CHANGELOG.md` 0.5.0 for when/why these were added.

## Going live (real money) - deliberately, later

`live_trade.py` has two independent locks against ever touching a real
account by accident:
1. `ALPACA_BASE_URL` must be explicitly changed to Alpaca's live endpoint
   (`https://api.alpaca.markets`) with real (non-paper) API keys.
2. I also have to pass `--i-understand-this-is-live` on the command line.

Both are required; neither alone will trade real money. I'm not flipping
these until I've watched the paper version run unattended for a
meaningful stretch (weeks to months) and I understand and accept its
drawdown behavior from the backtest results in `docs/RESEARCH.md`.

## Before this touches real money

1. **Re-run on real data, multiple tickers, multiple periods.** One
   ticker and one train/test split proves nothing. I need to loop over
   several tickers (different sectors, not just SPY) and several
   non-overlapping time windows, including at least one real bear market
   and one real bull run.
2. **Walk-forward validation**, not a single train/test split - test the
   same fixed rule across several separate, sequential real-data windows
   rather than trusting one lucky (or unlucky) period. `walk_forward.py`
   (see `docs/RESEARCH.md`) now does exactly this, and its first real
   use (2026-07-27, see `CHANGELOG.md` 0.7.0) is what the current live
   crypto thresholds are actually based on - a start, not the finish
   line: one round of validation over one real year isn't yet "multiple
   distinct periods including a real bear market and a real bull run,"
   the bar this checklist item is actually about.
3. **Paper trade it** against a live real-time feed (e.g. Alpaca's paper
   trading API) for at least a few months before any real capital is at
   risk. A backtest that looks good can still fail live due to slippage,
   fills, and regime changes a backtest can't see.
4. **Position sizing and risk limits** - beyond the `--max-notional` cap
   and daily-loss circuit breaker above, a real system would still
   benefit from portfolio-level diversification limits, not just
   per-trade/per-day bounds.
5. **Understand the failure mode going in**: this strategy is
   mean-reversion. It does reasonably in choppy, range-bound markets and
   can lose significantly in a sustained downtrend, where "the dip" just
   keeps dropping. I want to know that going in rather than discover it
   live.

The concrete bar for declaring this project past its `0.x.x` ("Version
Richards") line and into `1.0.0`+ is documented in `CHANGELOG.md`, along
with the full version-by-version history of every fix and addition that
got it here.
