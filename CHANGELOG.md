# Changelog

Uses [semantic versioning](https://semver.org/) (`MAJOR.MINOR.PATCH`).
The `0.x.x` line is "Version Richards"; `1.0.0`+ becomes "Version Giroux."

**What's required before `1.0.0` gets declared** (not yet met):
- Dozens to hundreds of real closed paper trades on the strategy
  actually running live - not the 3 currently on record, and none yet
  under the 0.7.0 thresholds - with positive net expectancy after real
  observed costs/slippage, not backtested ones.
- Walk-forward validation across multiple distinct, non-overlapping time
  periods, repeated more than once. `walk_forward.py` (added 0.6.2) did
  this for the first time in 0.7.0, across 6 real-data windows spanning
  Aug 2025-Jul 2026 - a real start, not the finish line. Still needed:
  re-validating as more live history accumulates, and explicit coverage
  of both a trending and a choppy/range-bound stretch, not just whatever
  regime the most recent real year happened to contain.
- No known open correctness bugs (true as of 0.5.2).

## Version Richards 0.8.0 - 2026-07-27

Stock automation paused; `optimize.py`/`walk_forward.py` can now
validate the stock side too.

- Paused: the cron-job.org jobs driving `paper-trade-stocks.yml` and
  `retrain-stock-model.yml` were paused, and the open QQQ position was
  closed manually on Alpaca. Cause: the account was carrying an
  unmanaged ~$33k QQQ position (about a third of its value) from an
  order that silently filled sometime after being submitted outside
  market hours - never logged, because `live_trade.py` only records a
  trade at the moment a run makes a fresh decision, not when an old
  pending order quietly clears later on its own. Investigating that
  also surfaced a real gap: unlike crypto, `paper-trade-stocks.yml`
  never had `--max-notional` or `--daily-loss-limit` wired in at all -
  nothing was capping how large a single stock position could grow.
  Crypto's cash, positions, and forward-test history under 0.7.0 are
  completely untouched by any of this - separate account activity, same
  underlying Alpaca account. `paper-trade-stocks.yml` itself is
  unmodified and can resume whenever the cron-job.org jobs are unpaused.
- Added: `optimize.py` and `walk_forward.py` both gained `--strategy
  {day_trading, rule_based}` (default `day_trading`, unchanged
  behavior). `rule_based` validates the dip/recovery-exit shape
  `ml_filtered` (the live stock strategy) is actually built on - a
  different parameter shape than crypto's dip/profit-target/stop-loss,
  which the live stock workflow's `--dip-threshold -0.03` was never
  actually validated against, just picked. No Alpaca data work needed
  for this - stocks run on daily bars, and Yahoo's daily history is
  already decades deep for SPY/AAPL/QQQ.
- Added: `position_for_params()` in `src/strategies.py` - the one place
  both scripts now get "which strategy takes which parameters" from,
  instead of each keeping its own copy of that mapping (the same reason
  `day_trading_decision` was factored out in 0.5.0).
- Added: 3 new tests in `tests/test_strategies.py` covering
  `position_for_params()`'s dispatch for both strategies plus the
  unknown-strategy error case.
- Read-only research-tooling change for the `--strategy` addition; no
  code change to live crypto trading. Stopping stock automation is a
  separate, external decision (a cron-job.org toggle, plus any manual
  position cleanup on Alpaca's own dashboard) - not a code change,
  `paper-trade-stocks.yml` itself is untouched either way and can resume
  the same way it was ever running.

## Version Richards 0.7.3 - 2026-07-27

- Updated README's opening framing: it stated flatly that the honest
  answer to "does this beat buy-and-hold" was no. As of 0.7.0 that's no
  longer the whole story - reworded to say a validated configuration may
  have found something real, meaningfully de-risked but not yet a proven
  steady edge (same phrase already used in "Current live status,"
  CHANGELOG 0.7.0, and both `docs/RISK.md`/`docs/RESEARCH.md` -
  consistent terminology throughout now), and is now running live
  specifically to gather forward evidence rather than trust the backtest
  alone. Still points to "Current live status" for the full picture and
  caveats, and still ties "real money" to real trade evidence, not
  backtested numbers. Documentation-only; no code or live-trading
  behavior changed.

## Version Richards 0.7.2 - 2026-07-27

Full sweep: comments, docs, and stale-reference check across everything
touched since 0.6.0.

- Fixed: `evaluate_combo()` in `optimize.py` was missing a docstring -
  every other function in the file has one.
- Fixed: `get_price_data_smart()` (`src/data.py`) silently fell through
  to Yahoo with no explanation when Alpaca returned too few bars for a
  range - the exception path already printed a reason, this one didn't.
  Now both do.
- Fixed: README's file tree still described `src/data.py` as
  "Yahoo Finance, with synthetic fallback" only, and `results/` didn't
  mention `walk_forward.csv` or either chart PNG - both now match what's
  actually there.
- Fixed: the `1.0.0` requirements list at the top of this file still said
  walk-forward validation across multiple periods hadn't happened at
  all - it has now, once, as of 0.7.0. Reworded to say what's actually
  been done (one real round) versus what's still missing (repeating it,
  and explicit trending/choppy regime coverage).
- Fixed: `docs/RISK.md`'s pre-real-money checklist described
  walk-forward validation as a pending, ML-flavored idea (retrain on a
  rolling window) - `walk_forward.py` does something both simpler and
  already real (fixed-rule testing across sequential windows) and has
  now actually been used once; the checklist item now says so.
- No other bugs found; everything else (all doc cross-references,
  markdown links, image paths) re-verified clean.

## Version Richards 0.7.1 - 2026-07-27

- Added: `results/param_sweep_overview.png` and
  `results/walk_forward_winner.png` - rendered charts of the 0.7.0
  evidence CSVs, generated straight from `results/param_sweep.csv` and
  `results/walk_forward.csv` (not hand-edited), embedded in README's
  "Current live status" and `docs/RESEARCH.md`'s worked example. The
  scatter plot makes the "trading less often did better" pattern visible
  at a glance; the small-multiples grid makes clear where the 0.7.0
  combo's gains are concentrated (two specific calendar windows across
  several coins), the same caveat already in the 0.7.0 writeup, now
  visible instead of just described.
- Documentation-only; no code or live-trading behavior changed.

## Version Richards 0.7.0 - 2026-07-27

**Live crypto trading rules changed** - the first threshold change since
0.5.0 backed by real validation evidence, not a guess.

- Changed: `.github/workflows/paper-trade-crypto.yml` now runs
  `day_trading` with **`--dip-threshold -0.04 --profit-target 0.01
  --stop-loss 0.05`**, replacing the prior `-0.01 / 0.01 / 0.03`. The
  old combo bought on any 1%+ dip, which fires constantly on 5-minute
  bars - a `walk_forward.py` run across a real year of Alpaca data (see
  below) found it losing money in 53 of 54 ticker/window combinations,
  often placing 100-1,000+ trades per ticker in a single ~2-month
  window at a real ~0.2-0.4% round-trip fee floor. The new -4% threshold
  only buys real, comparatively rare dips - the same backtest period
  saw just 4-52 trades per ticker over the full year - trading the fee
  drag away rather than fighting it. `--profit-target`/`--stop-loss`
  also widened (1%/5% vs 1%/3%) to give a genuine 4%+ dip room to bounce
  without an early stop-out. `--max-notional` ($2,000) and
  `--daily-loss-limit` (5%) are unchanged.
- Added: `results/param_sweep.csv` - the full 90-combination grid search
  (`optimize.py`, real Alpaca 5-minute data, 2025-08-01 to 2026-07-27)
  that surfaced this combo as the best average-return result, with its
  closest neighbors (same dip/profit, different stop) landing within a
  couple points of each other - the "not an isolated overfit spike"
  check `docs/RESEARCH.md` describes.
  `worst_ticker_return` on the top two rows is **positive** - every one
  of the 9 coins was profitable, not just the average.
- Added: `results/walk_forward.csv` - the walk-forward validation of
  this specific combo (`walk_forward.py`, same real data, split into 6
  sequential ~2-month windows). 49 of 54 ticker/window results were
  non-negative (vs. 1 of 54 for the old combo) - a real, large
  improvement, though not an unqualified one: a large share of the
  total gain is concentrated in two specific windows
  (2025-09-30→2025-11-29 and 2026-01-28→2026-03-29) where several
  unrelated coins moved together, suggesting broad market-wide swings
  rather than an independent per-coin edge, and a couple of the winning
  windows (LTC, LINK) show large intra-window drawdowns (-37.7%, -31.8%)
  that the final window return doesn't show. Read as "meaningfully
  de-risked versus what was live before," not yet "a proven, steady
  edge" - see README's "Current live status" for the same caveat in
  context.
- Added: `walk_forward.py` now writes its own results to
  `results/walk_forward.csv` (`--out` to change the path), matching
  `optimize.py`'s existing `results/param_sweep.csv` output - every
  future validation run is now a durable, committable record instead of
  console output that scrolls away.

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
