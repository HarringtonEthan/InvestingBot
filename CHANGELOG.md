# Changelog

Uses [semantic versioning](https://semver.org/) (`MAJOR.MINOR.PATCH`) -
staying under `1.0.0` on purpose until the strategy has actually
demonstrated a real edge on real data, not just that the code runs
correctly.

## Version Richards 0.5.0 - 2026-07-27

Test suite, a shared decision function, and two real risk controls -
the first two don't change crypto's behavior at all, the last two do.

- Added: `tests/` - 40 pytest tests covering RSI, label leakage, symbol
  resolution, backtest annualization, broker error handling, and the
  new shared decision logic below
- Added: `day_trading_decision()` in `src/strategies.py` - the one
  place the day-trading buy/sell/hold rule now lives, called by both
  the backtest (`dip_buy_profit_target`) and live trading (`decide()`)
  instead of each keeping its own copy that could quietly drift apart.
  Verified behavior-preserving against the old logic across 200,000
  randomized scenarios before going live - a pure refactor, not a
  strategy change
- Added: a daily-loss circuit breaker (`--daily-loss-limit`, default
  5%) - blocks new BUYs for the rest of the day once the account is
  down 5%+ from that day's starting equity; never blocks SELLs
- Added: `--max-notional` is now actually wired into the live crypto
  workflow (capped at $2,000/trade) - it existed as a flag before but
  was never passed by the workflow itself

## Version Richards 0.4.0 - 2026-07-27

Measurement and reliability audit - no changes to the actual crypto
trading rules (-1% dip / +1% profit / -3% stop are untouched).

- Fixed: RSI defaulted to neutral 50 during a pure uptrend instead of
  the correct 100, muting the strongest bullish signal (stock ML model only)
- Fixed: the ML model's training labels silently fabricated "didn't
  bounce" for rows with an incomplete lookahead window instead of
  excluding them (stock ML model only)
- Fixed: backtest annualized return/vol/Sharpe hardcoded 252 trading
  days/year regardless of the actual bar interval - wrong for intraday
  backtests (research tools only, not live trading)
- Fixed: `--cost-bps` help text called it a "round-trip cost" when it's
  actually charged on every position change (twice per round trip) -
  corrected the documentation, not the math, which was already right
- Fixed: broker position lookups treated every API error as "no
  position held," including real auth/rate-limit/server failures, not
  just genuine 404s
- Fixed: one ticker's API failure could crash the entire live run,
  silently skipping every other ticker scheduled that cycle
- Fixed: orders were logged as "placed" the instant they were
  submitted, not when actually filled - now polls for real fill
  confirmation and logs the actual fill price when available
- Added: `timeout-minutes` on all 4 GitHub Actions workflows
- Added: pinned `requirements.txt` to exact known-working versions
- Added: real-data fetch failures now print instead of failing silently

## Version Richards 0.3.0 - 2026-07-25

Bugs found from watching real live trades, not code review.

- Fixed a critical bug: crypto positions were invisible to the bot
  because Alpaca's client builds position-lookup URLs by plain string
  concatenation, and a symbol like `DOGE/USD` broke that path - the bot
  could never detect a crypto position it already held
- Fixed: BUY signals could stack a duplicate order on top of an
  already-open, unfilled order (found via two real stale QQQ orders)
- Fixed: `--dip-threshold` was silently ignored by `rule_based` and
  `ml_filtered`, always using a hardcoded 3% dip regardless of what was
  passed on the command line
- Reworked trade/equity logging into separate files with a manual
  `notes` flagging system, so an anomalous trade can be documented
  without deleting or hiding it
- Added the hourly-updating trade dashboard

## Version Richards 0.2.0 - 2026-07-25

- Added crypto support (BTC, ETH, SOL, DOGE, LTC, and more)
- Added GitHub Actions workflows for always-on automated paper trading,
  with an external scheduler (cron-job.org) working around GitHub's own
  unreliable `schedule:` trigger
- Added the day-trading strategy (profit-target/stop-loss exits from
  actual entry price) used for live crypto trading
- Added the Bollinger Band breakout strategy (implemented, not deployed)
- Added `optimize.py` for multi-ticker parameter sweeps

## Version Richards 0.1.0 - 2026-07-24

- Initial backtest engine, five trading strategies, and the ML dip-filter
- Initial automated paper trading against Alpaca (stocks)
