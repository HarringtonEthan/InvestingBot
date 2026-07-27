# Changelog

Uses [semantic versioning](https://semver.org/) (`MAJOR.MINOR.PATCH`).
The `0.x.x` line is "Version Richards"; `1.0.0`+ becomes "Version Giroux."

**What's required before `1.0.0` gets declared** (not yet met):
- Dozens to hundreds of real closed paper trades on the strategy
  actually running live - not the 3 currently on record - with positive
  net expectancy after real observed costs/slippage, not backtested
  ones.
- Walk-forward validation across multiple distinct, non-overlapping time
  periods (including at least one trending and one choppy/range-bound
  stretch), not just the single window the current thresholds were
  picked on.
- No known open correctness bugs (true as of 0.5.2).

## Version Richards 0.6.3 - 2026-07-27

- Added: `optimize.py` now also pulls crypto history from Alpaca first
  via `get_price_data_smart()`, the same data path added to
  `walk_forward.py` in 0.6.2 - the parameter-sweep grid search can now
  run over a genuine year or more of real 5-minute crypto data instead
  of Yahoo Finance's ~60-day intraday cap. Each ticker's data-loading
  line now shows which source served it.
- Context: a `walk_forward.py` run against a full year of real Alpaca
  data (not yet possible before 0.6.2) found the live -1%/+1%/-3% combo
  losing money in the large majority of windows across nearly every
  coin, often with very high trade counts (100-300+ in a single
  ~2-month window) suggesting transaction-cost drag as a real
  contributor. `docs/RESEARCH.md` now documents re-running `optimize.py`
  over this same real data, searching toward less-frequent-trading
  combos, as the concrete next step - not yet done, and the live
  -1%/+1%/-3% thresholds are unchanged pending that.
- Read-only research-tooling change; no live crypto trading behavior
  affected.

## Version Richards 0.6.2 - 2026-07-27

- Added: `walk_forward.py` now pulls crypto history from **Alpaca first**
  instead of only Yahoo Finance, via a new `get_price_data_smart()` in
  `src/data.py`. Yahoo's intraday history is capped at roughly 60 days
  regardless of ticker, which made a real multi-window validation of the
  5-minute crypto strategy impossible past that; Alpaca (the actual
  venue this project trades against) isn't subject to that same
  free-tier retention limit, so a much longer `--start` can now work for
  crypto specifically. Falls back to Yahoo, then synthetic (skipped), if
  Alpaca has too little data for a given range - each window's output
  now shows exactly which source served it (`alpaca`/`yahoo`), so a
  fallback is visible, not silent.
- Added: `src/alpaca_data.py`'s `get_crypto_bars()` (live trading) was
  refactored to share its bar-fetching logic with the new
  `get_crypto_bars_range()` (historical/backtesting) instead of
  duplicating it - behavior-preserving for live trading, which still
  goes through the exact same staleness check as before.
- Added: `tests/test_data.py` - covers `get_price_data_smart()`'s
  routing (Alpaca-first for crypto, straight-to-Yahoo for stocks, and
  the fallback chain when Alpaca comes up short or unreachable).
- Read-only research-tooling change; no live crypto trading behavior
  affected - `live_trade.py`'s own price-fetching path is untouched.

## Version Richards 0.6.1 - 2026-07-27

Documentation restructure - no code or live-trading behavior changed.

- The README had grown to nearly 1,400 lines trying to serve three
  different audiences at once (portfolio reviewers, contributors,
  complete beginners), which made the important information hard to
  find. Split it into a short overview README plus four focused docs:
  `docs/BEGINNER_GUIDE.md` (plain-English walkthrough + glossary),
  `docs/AUTOMATION.md` (GitHub Actions/cron-job.org setup, logs and
  dashboard), `docs/RISK.md` (risk controls, real-money requirements),
  `docs/RESEARCH.md` (backtesting, strategies/ML detail, `optimize.py`,
  `walk_forward.py`).
- "Current live status" now leads with a compact scorecard table
  instead of only prose.
- Removed the bug-fix narrative bullets and the embedded "Version
  history" section from the README - that content already existed,
  word-for-word in spirit, in `CHANGELOG.md`. Versions now live only in
  the changelog; the README keeps just the current version number at
  the top.
- Fixed stale `README.md`-section cross-references in `live_trade.py`,
  `train_stock_model.py`, `visualize_log.py`, and two workflow files to
  point at the new doc locations.

## Version Richards 0.6.0 - 2026-07-27

- Added: `walk_forward.py` - splits a date range into several
  sequential, non-overlapping windows and re-scores a fixed
  dip/profit/stop combination independently on each one, instead of the
  single train/test split `main.py`/`optimize.py` use. A combo that only
  looks good on one window can still be luck; this is the "walk-forward
  validation across multiple distinct, non-overlapping time periods"
  named above as a 1.0.0 requirement. Defaults to the exact parameters
  the live crypto workflow trades with, so it validates the strategy
  actually running, not a hypothetical one. Read-only research tool -
  no change to live crypto behavior, and the -1%/+1%/-3% thresholds
  themselves are untouched pending more real trade history.
- Added: `tests/test_walk_forward.py` - covers the window-splitting
  logic (sequential, non-overlapping, covers the full requested range).

## Version Richards 0.5.2 - 2026-07-27

Full codebase sweep (every `src/*.py` file, `live_trade.py`, `main.py`,
`optimize.py`, `train_stock_model.py`, `visualize_log.py`, all 4
workflow files, and every test) re-read line by line looking for bugs
and comment gaps.

- Fixed: `--max-notional 0` was silently treated the same as
  `--max-notional` not being passed at all, because `if args.max_notional:`
  treats 0 and None identically in Python - an explicit zero cap should
  mean "never buy," not "fall back to the uncapped per-ticker split."
  Extracted into a small, directly-tested `compute_buy_budget()`
  function so this class of truthiness bug can't quietly return. Zero
  effect on current live behavior (the configured cap is $2,000, not 0).
- No other bugs found; everything else re-verified clean.

## Version Richards 0.5.1 - 2026-07-27

Bug found during a follow-up audit of 0.5.0's own changes.

- Fixed: `starting_cash = broker.get_cash()`, the circuit breaker's
  `broker.get_equity()` call, and the final per-run equity logging call
  had no error handling, unlike every per-ticker call - a transient
  Alpaca API failure on any of those three specific calls would still
  have crashed the entire run instead of failing gracefully and letting
  the next scheduled run retry. Wrapped in try/except, same pattern as
  the per-ticker isolation added in 0.4.0.
- Also brought `tests/fake_broker.py` and two other test files up to
  the same line-by-line comment standard as the rest of the codebase.

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
