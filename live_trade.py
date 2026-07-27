"""
Run one automated trading decision, for one or more tickers, against an
Alpaca account (paper by default) and, if a position needs to change,
place the order.

Meant to be run on a schedule via cron / Task Scheduler / GitHub Actions -
see docs/AUTOMATION.md for setup. Each run is
stateless: it re-derives that period's buy/sell/hold decision from price
history and your *actual* broker position for each ticker, so it's safe
to run it manually as many times as you want to check what it would do.

Safety defaults:
  - Points at Alpaca's PAPER endpoint unless ALPACA_BASE_URL is changed.
  - Refuses to submit real orders unless --execute is passed; without it,
    it prints what it *would* do and stops.
  - Refuses to touch a live account at all unless you also pass
    --i-understand-this-is-live (on top of changing ALPACA_BASE_URL).
  - Aborts a ticker instead of trading it on synthetic/fallback data.
"""

# Lets type hints work without issue in this Python version.
from __future__ import annotations

# argparse for command-line flags; csv for reading/writing the log files;
# datetime for timestamps; time for the brief post-order fill-polling
# pause; Path for file handling.
import argparse
import csv
import datetime as dt
import time
from pathlib import Path

# Loads ALPACA_API_KEY / ALPACA_SECRET_KEY / ALPACA_BASE_URL from a local
# .env file into the environment, so they don't need to be exported by hand.
from dotenv import load_dotenv

# The status value that means an order has actually been executed - used
# to distinguish a confirmed fill from a merely-submitted order.
from alpaca.trading.enums import OrderStatus

# Alpaca-sourced crypto price bars (used instead of Yahoo for crypto - see
# module docstring in src/alpaca_data.py).
from src.alpaca_data import get_crypto_bars
# The Alpaca account/order wrapper.
from src.broker import Broker
# Yahoo Finance (or synthetic fallback) price data, used for stocks.
from src.data import get_price_data
# Technical indicator computation.
from src.features import add_features
# Inline ML model training, used as a fallback if no saved model exists.
from src.model import train_model
# Loading a previously-trained-and-saved ML model from disk.
from src.model_store import load_model as load_saved_model
# The trading strategies this script can be told to run. day_trading_decision
# is the single-step rule day_trading uses below - shared with the backtest
# version of the same strategy (dip_buy_profit_target) so the two can never
# quietly drift apart from each other.
from src.strategies import bollinger_breakout, day_trading_decision, ml_filtered_dip_buy, rule_based_dip_buy
# Resolves a bare ticker string into its Yahoo/Alpaca symbol forms.
from src.symbols import resolve_symbol

# Where every actual BUY/SELL decision gets appended as a row.
TRADE_LOG_PATH = Path("logs/trade_log.csv")
# Fixed column order for trade_log.csv - see the comment on _append_row
# below for why this is a fixed list rather than derived from each row.
TRADE_LOG_FIELDS = [
    "timestamp_utc", "mode", "asset_class", "ticker", "strategy",
    "action", "price_usd", "notional_usd", "position_qty_before",
    "avg_entry_price_usd", "unrealized_gain_pct", "order_placed", "notes",
]
# "notes" is never auto-populated by the bot - it's a manual annotation
# slot for flagging a specific trade as unrepresentative (e.g. inflated
# by a since-fixed bug), so visualize_log.py can show both "as it
# happened" and "excluding known anomalies" without ever deleting or
# hiding the real data.

# Deliberately separate from trade_log.csv and always one row per run (not
# per ticker): trade_log.csv only records actual BUY/SELL decisions - most
# runs are HOLD and aren't logged at all, to keep both the file size and
# the number of git commits (one per run, since these get committed by the
# GitHub Actions workflows) from growing unboundedly on the 5-minute crypto
# schedule. This file is what an equity-over-time chart should read from.
EQUITY_LOG_PATH = Path("logs/equity_log.csv")
EQUITY_LOG_FIELDS = ["timestamp_utc", "mode", "portfolio_value_usd", "cash_usd"]

# Yahoo Finance limits how far back intraday bars go (roughly; exact
# limits can change). These defaults stay safely inside those limits;
# override with --lookback-days if you know your interval supports more.
DEFAULT_LOOKBACK_DAYS = {"1d": 365 * 5, "4h": 90, "1h": 59, "30m": 59, "15m": 59, "5m": 7}


def get_target_position(df, args) -> float:
    strategy = args.strategy
    if strategy == "rule_based":
        # --exit-threshold/--rule-stop-loss/--rule-stop-cooldown mirror
        # walk_forward.py's/optimize.py's own flag names exactly, so a
        # combo validated there can be deployed here with the same
        # numbers, no translation - stop_loss/stop_cooldown_bars default
        # to None/0 (rule_based_dip_buy's own defaults) if never passed,
        # so omitting them keeps the original mean-reversion-only behavior.
        series = rule_based_dip_buy(
            df, dip_threshold=args.dip_threshold, exit_threshold=args.exit_threshold,
            stop_loss=args.rule_stop_loss, stop_cooldown_bars=args.rule_stop_cooldown or 0,
        )
    elif strategy == "ml_filtered":
        # Prefer a model that was trained ahead of time and saved to disk
        # (via train_stock_model.py on a schedule) over training one from
        # scratch on every single live run.
        saved = load_saved_model(args.model_path) if args.model_path else None
        if saved is not None:
            model, threshold, meta = saved
            print(f"[ml_filtered] Using saved model from {args.model_path} "
                  f"(trained {meta.get('trained_at', '?')} on {meta.get('tickers', '?')})")
        else:
            # No saved model found - fall back to training inline just for
            # this run, but warn that this result won't persist.
            print(f"[ml_filtered] No saved model at {args.model_path!r} - training one inline "
                  f"from just this run's data instead (won't persist between runs). Run "
                  f"train_stock_model.py on a schedule to avoid this - see README.md.")
            model, threshold, _ = train_model(df)
        # ml_filtered_dip_buy has no stop-loss/cooldown of its own (see
        # src/strategies.py) - only dip/exit apply here.
        series = ml_filtered_dip_buy(
            df, model, threshold, dip_threshold=args.dip_threshold, exit_threshold=args.exit_threshold,
        )
    elif strategy == "bollinger_breakout":
        series = bollinger_breakout(
            df, bb_window=args.bb_window, bb_std=args.bb_std, trend_window=args.trend_window,
        )
    else:
        raise ValueError(f"unknown strategy: {strategy}")
    # Only the most recent bar's decision matters for a live run - past
    # bars in the series were just needed to compute it correctly.
    return float(series.iloc[-1])


def _append_row(path: Path, fieldnames: list[str], row: dict):
    # fieldnames is always the fixed module-level list above, never derived
    # from row.keys() - a prior version did that, and once the row shape
    # changed after the file (and its header) already existed, every
    # subsequent row silently drifted out of alignment with its own header.
    path.parent.mkdir(parents=True, exist_ok=True)
    # Whether the file exists yet, checked before opening it, decides
    # whether a header row needs to be written first.
    is_new = not path.exists()
    # "a" = append mode (never overwrites existing rows); newline="" is
    # required by Python's csv module to avoid extra blank lines on Windows.
    with path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if is_new:
            writer.writeheader()
        writer.writerow(row)


def log_trade(row: dict):
    _append_row(TRADE_LOG_PATH, TRADE_LOG_FIELDS, row)


def _last_equity_values() -> tuple[str, str] | None:
    """Returns (portfolio_value_usd, cash_usd) from the last row of the
    equity log, or None if the file doesn't exist yet / has no data rows."""
    if not EQUITY_LOG_PATH.exists():
        return None
    with EQUITY_LOG_PATH.open(newline="") as f:
        # Read every row into a list of dicts (one dict per row, keyed by
        # the header column names) so the last one can be grabbed easily.
        rows = list(csv.DictReader(f))
    if not rows:
        return None
    last = rows[-1]
    return last["portfolio_value_usd"], last["cash_usd"]


def log_equity(row: dict):
    # Most runs change nothing (no trade, no price movement in an open
    # position) - skip the row entirely when the account value is exactly
    # what it was last time, rather than writing an identical line every
    # 5 minutes forever. A real change (even a small one) still gets
    # logged immediately.
    if _last_equity_values() == (row["portfolio_value_usd"], row["cash_usd"]):
        return
    _append_row(EQUITY_LOG_PATH, EQUITY_LOG_FIELDS, row)


def _first_equity_today(now: dt.datetime) -> float | None:
    """
    Returns the first portfolio_value_usd logged today (UTC calendar
    day), or None if nothing's been logged yet today - e.g. the very
    first run of the day, or a completely flat day where log_equity()
    never wrote a row. None means "no baseline to compare against yet,"
    not "no loss" - callers should treat that as "can't check, allow
    trading" rather than blocking on missing data.
    """
    if not EQUITY_LOG_PATH.exists():
        return None
    with EQUITY_LOG_PATH.open(newline="") as f:
        rows = list(csv.DictReader(f))
    today = now.date().isoformat()
    for row in rows:
        # timestamp_utc looks like "2026-07-27T00:01:00+00:00" - the
        # date portion is always the first 10 characters.
        if row["timestamp_utc"][:10] == today:
            return float(row["portfolio_value_usd"])
    return None


def daily_loss_exceeded(broker: Broker, threshold_pct: float) -> bool:
    """
    True if the account is currently down threshold_pct or more from
    today's first logged equity value - a simple circuit breaker so a
    genuinely bad day can't compound itself by continuing to open new
    positions. Only ever blocks new BUYs (see main() below) - an
    existing position's own profit-target/stop-loss exit still runs
    normally, since cutting a loss is exactly what should keep
    happening even on a day this breaker has tripped.
    """
    day_start_equity = _first_equity_today(dt.datetime.now(dt.timezone.utc))
    if day_start_equity is None or day_start_equity <= 0:
        # No baseline yet today - nothing to compare against, so don't
        # block trading over missing data.
        return False
    current_equity = broker.get_equity()
    drawdown = (day_start_equity - current_equity) / day_start_equity
    return drawdown >= threshold_pct


def compute_buy_budget(per_ticker_budget: float, max_notional: float | None) -> float:
    """
    How much a single BUY is allowed to spend: the even per-ticker split,
    capped by --max-notional if one was given. Checks `is not None`, not
    plain truthiness - an explicit --max-notional 0 must mean "cap every
    buy at $0" (never buy), not silently fall back to the uncapped split
    the way `if max_notional:` would (0 is falsy in Python).
    """
    if max_notional is not None:
        return min(per_ticker_budget, max_notional)
    return per_ticker_budget


def poll_for_fill(broker: Broker, order, attempts: int = 3, delay_seconds: float = 2.0):
    """
    Briefly poll Alpaca for whether a just-submitted order has actually
    filled, instead of assuming submission == execution (a market order
    can take a moment, or - as happened with two real QQQ orders in this
    project's history - never fill at all if submitted outside market
    hours). Returns (filled, filled_qty, filled_avg_price); the last two
    are None if it hasn't filled within the polling window - that's a
    legitimate outcome (it may still fill later on its own), not an error.
    """
    for attempt in range(attempts):
        # No need to sleep before the very first check - the order may
        # already be filled by the time submit_order() returned.
        if attempt > 0:
            time.sleep(delay_seconds)
        current = broker.get_order(order.id)
        if current.status == OrderStatus.FILLED:
            return True, float(current.filled_qty), float(current.filled_avg_price)
    return False, None, None


def decide(ticker: str, args, broker: Broker):
    """Returns a dict describing the decision for one ticker, or None if data was unusable."""
    # Figures out both the Yahoo-format and Alpaca-format symbol strings,
    # and whether this ticker is crypto or a stock/ETF.
    symbol = resolve_symbol(ticker)
    # Use the explicit --lookback-days if given, otherwise pick a sane
    # default for whatever bar interval was requested.
    lookback_days = args.lookback_days or DEFAULT_LOOKBACK_DAYS.get(args.interval, 30)

    if symbol.is_crypto:
        # Alpaca's own crypto feed, not Yahoo Finance: Yahoo's intraday
        # crypto bars can silently go stale for hours without erroring,
        # which is worse than a hard failure. Alpaca is also the actual
        # execution venue, so "current price" means what it says.
        try:
            raw = get_crypto_bars(symbol.alpaca, args.interval, lookback_days)
        except Exception as e:
            # Any failure fetching crypto bars (network error, stale-data
            # rejection, etc.) - skip this ticker for this run rather than
            # crash the whole script over one bad ticker.
            print(f"[{ticker}] SKIPPED: {e}")
            return None
    else:
        # Stocks use plain Yahoo Finance, looking back lookback_days from today.
        end = dt.date.today()
        start = end - dt.timedelta(days=lookback_days)
        raw, is_synthetic = get_price_data(symbol.yfinance, start.isoformat(), end.isoformat(), interval=args.interval)
        if is_synthetic:
            # Never trade real (paper) money on made-up fallback data -
            # bail out for this ticker if Yahoo Finance wasn't reachable.
            print(f"[{ticker}] SKIPPED: only synthetic fallback data was available "
                  f"(no real network access to Yahoo Finance from here).")
            return None

    # Compute technical indicators on whatever price data was fetched.
    df = add_features(raw)
    # The most recent closing price and the timestamp it belongs to -
    # what the trading decision is actually based on.
    last_price = float(df["Close"].iloc[-1])
    last_date = df.index[-1]

    # Ask the broker (Alpaca, ground truth) how much of this asset is
    # actually currently held - not derived from the log file, which
    # could be stale or incomplete.
    current_qty = broker.get_position_qty(symbol.alpaca)
    currently_holding = current_qty > 0

    entry_price = None
    gain_pct = None
    pct_below = None

    if args.strategy == "day_trading":
        # How far below (negative) or above the 20-period average price
        # currently sits - the dip signal this strategy buys on.
        pct_below = float(df["pct_below_sma20"].iloc[-1])
        if currently_holding:
            # Already holding - the real cost basis comes from the
            # broker's actual average entry price (not the moving
            # average, which is irrelevant to actual P&L).
            entry_price = broker.get_position_avg_entry_price(symbol.alpaca)
        if currently_holding and not entry_price:
            # Held according to Alpaca, but its own entry-price lookup
            # came back empty (shouldn't normally happen) - can't
            # compute a gain without it, so do nothing this run rather
            # than guess.
            action = "HOLD"
        else:
            # Same single-step rule the backtest version of this
            # strategy uses (see day_trading_decision in
            # src/strategies.py) - both call this exact function so live
            # trading and a backtest of "day trading" can never quietly
            # diverge from each other.
            action = day_trading_decision(
                currently_holding, entry_price, last_price, pct_below,
                args.dip_threshold, args.profit_target, args.stop_loss,
            )
        if currently_holding and entry_price:
            gain_pct = last_price / entry_price - 1.0
        # Express the decision as a target position fraction too, for
        # consistency with the other strategies' return shape (even
        # though day_trading's own action/entry-price logic above is
        # what actually drives behavior).
        target_position = 1.0 if (action == "BUY" or (action == "HOLD" and currently_holding)) else 0.0
    else:
        # The other strategies work purely off a computed target position
        # fraction (0.0 = flat, 1.0 = fully in) rather than day_trading's
        # entry-price-aware profit target/stop loss logic.
        target_position = get_target_position(df, args)
        if target_position >= 1.0 and not currently_holding:
            action = "BUY"
        elif target_position <= 0.0 and currently_holding:
            action = "SELL"
        else:
            action = "HOLD"

    return {
        "ticker": ticker,
        "symbol": symbol,
        "last_price": last_price,
        "last_date": last_date,
        "target_position": target_position,
        "current_qty": current_qty,
        "entry_price": entry_price,
        "gain_pct": gain_pct,
        "pct_below_sma20": pct_below,
        "action": action,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", nargs="+", default=["SPY"],
                         help="one or more tickers, space-separated, e.g. --ticker SPY AAPL QQQ")
    parser.add_argument("--strategy", choices=["rule_based", "ml_filtered", "day_trading", "bollinger_breakout"], default="rule_based")
    parser.add_argument("--model-path", default="models/stock_model.pkl",
                         help="ml_filtered: saved model to load (see train_stock_model.py). "
                              "Falls back to training inline if this path doesn't exist yet.")
    parser.add_argument("--interval", default="1d",
                         help="bar size for price data: 1d, 4h, 1h, 30m, 15m, 5m (4h only works for crypto, via Alpaca)")
    parser.add_argument("--lookback-days", type=int, default=None,
                         help="history to pull; default depends on --interval (see DEFAULT_LOOKBACK_DAYS)")
    parser.add_argument("--dip-threshold", type=float, default=-0.02,
                         help="all strategies except bollinger_breakout: buy when price is this "
                              "fraction below its rolling average, e.g. -0.02 = 2%% dip")
    parser.add_argument("--exit-threshold", type=float, default=0.0,
                         help="rule_based/ml_filtered only - how far above/below the rolling average "
                              "counts as 'recovered enough to sell' (0.0 = back at the average). "
                              "Matches optimize.py's/walk_forward.py's own --exit-threshold flag name, "
                              "so a validated combo can be deployed here with the same number.")
    parser.add_argument("--rule-stop-loss", type=float, default=None,
                         help="rule_based only, optional - a hard stop-loss (fraction below entry "
                              "price), the same downside cap day_trading always has via --stop-loss. "
                              "A separate flag since ml_filtered_dip_buy doesn't support one at all. "
                              "Omit to trade without one (the original mean-reversion-only behavior).")
    parser.add_argument("--rule-stop-cooldown", type=int, default=None,
                         help="rule_based only, optional (needs --rule-stop-loss too) - how many bars "
                              "to wait before re-buying after a stop-loss exit. Without this, a "
                              "stop-loss can immediately re-trigger during a sustained decline instead "
                              "of actually protecting capital - see optimize.py's --stop-loss-values "
                              "help text for the real example that motivated this.")
    parser.add_argument("--profit-target", type=float, default=0.02,
                         help="day_trading: sell once price is this fraction above your actual entry price")
    parser.add_argument("--stop-loss", type=float, default=0.04,
                         help="day_trading: sell if price falls this fraction below your actual entry price")
    parser.add_argument("--bb-window", type=int, default=20,
                         help="bollinger_breakout: period for the middle band / exit SMA")
    parser.add_argument("--bb-std", type=float, default=2.0,
                         help="bollinger_breakout: standard deviations for the upper band")
    parser.add_argument("--trend-window", type=int, default=200,
                         help="bollinger_breakout: long SMA period required to confirm a breakout")
    parser.add_argument("--max-notional", type=float, default=None,
                         help="cap $ amount per buy; default = an even split of available cash across tickers")
    parser.add_argument("--daily-loss-limit", type=float, default=0.05,
                         help="circuit breaker: block new BUYs (not SELLs) once the account is down this "
                              "fraction from today's first logged equity value, e.g. 0.05 = 5%%. "
                              "Existing positions' own profit-target/stop-loss exits still run normally.")
    parser.add_argument("--execute", action="store_true", help="actually submit orders; without this, dry-run only")
    parser.add_argument("--i-understand-this-is-live", action="store_true", dest="allow_live")
    args = parser.parse_args()

    # Populate environment variables (ALPACA_API_KEY etc.) from .env, if present.
    load_dotenv()

    # Constructing the Broker enforces the paper/live safety checks
    # described in the module docstring above.
    broker = Broker(allow_live=args.allow_live)
    mode = "PAPER" if broker.is_paper else "LIVE"

    tickers = args.ticker
    decisions = []
    for ticker in tickers:
        try:
            # decide() may return None (data unusable/skipped) - only keep
            # the tickers that produced an actual decision.
            decision = decide(ticker, args, broker)
            if decision is not None:
                decisions.append(decision)
        except Exception as e:
            # One ticker's API call failing (network blip, rate limit,
            # etc.) used to have no containment here - an uncaught
            # exception from decide() would crash the whole run, silently
            # skipping every other ticker for this cycle too, not just the
            # one that failed. Catch, report, and move on instead.
            print(f"[{ticker}] ERROR during decide(): {type(e).__name__}: {e} - skipping this ticker this run.")

    # Everything below needs the broker's account-level endpoints
    # (get_cash/get_equity) to actually respond - unlike the per-ticker
    # calls above and below, which are each individually isolated, a
    # single account-level call failing here used to have no
    # containment of its own and would crash the entire run outright.
    # Wrapped the same way: report clearly and stop this run cleanly
    # rather than an unhandled traceback - the next scheduled run 5
    # minutes later will simply try again.
    try:
        # Split whatever cash is available evenly across tickers being
        # watched this run, so several simultaneous BUY signals don't
        # let the first one spend the whole account.
        starting_cash = broker.get_cash()
        per_ticker_budget = starting_cash / len(tickers) if tickers else 0.0

        # Checked once per run, not per ticker - the account is either
        # having a bad enough day or it isn't, regardless of which ticker
        # is being evaluated. Only ever blocks new BUYs below; SELLs
        # (including a strategy's own profit-target/stop-loss exit) are
        # never blocked by this, since letting an existing position ride
        # out a bad day unmanaged would be the opposite of what a
        # circuit breaker is for.
        breaker_tripped = args.execute and daily_loss_exceeded(broker, args.daily_loss_limit)
        if breaker_tripped:
            print(f"[circuit breaker] Account is down {args.daily_loss_limit:.0%}+ from today's starting equity - "
                  f"blocking new BUYs for the rest of the run. SELLs are unaffected.")
    except Exception as e:
        print(f"ERROR fetching account info: {type(e).__name__}: {e} - aborting this run, will retry next cycle.")
        return

    for decision in decisions:
        ticker = decision["ticker"]
        symbol = decision["symbol"]
        action = decision["action"]

        try:
            kind = "crypto" if symbol.is_crypto else "stock"
            gain_str = f"  unrealized={decision['gain_pct']:+.2%}" if decision["gain_pct"] is not None else ""
            # When not holding, gain_pct is always None (nothing to compute a
            # gain on) - show how close price is to the dip threshold instead,
            # so "is it about to buy this?" has an actual answer in the log.
            dip_str = ""
            if decision["gain_pct"] is None and decision["pct_below_sma20"] is not None and args.strategy == "day_trading":
                dip_str = f"  vs_20period_avg={decision['pct_below_sma20']:+.2%} (buys at {args.dip_threshold:+.2%})"
            print(f"[{mode}] {ticker} ({kind}) as of {decision['last_date']}: price=${decision['last_price']:.2f}  "
                  f"strategy={args.strategy}  current_qty={decision['current_qty']}{gain_str}{dip_str}  -> {action}")

            executed = False
            notional = None
            # The logged trade price - starts as the decision-time market
            # price, replaced below with the real confirmed fill price
            # when poll_for_fill() finds one; see its docstring above.
            fill_note = ""
            fill_price = decision["last_price"]
            if action != "HOLD" and args.execute:
                if action == "BUY":
                    if breaker_tripped:
                        # Circuit breaker already reported once above -
                        # just skip this specific BUY without repeating
                        # the same message once per ticker.
                        print(f"[{ticker}] Skipping BUY - daily loss circuit breaker is active.")
                    elif broker.has_open_order(symbol.alpaca):
                        # Already an unfilled order sitting out there for this
                        # symbol (e.g. a DAY order queued after market close) -
                        # don't stack a second one on top of it.
                        print(f"[{ticker}] Skipping BUY - an order for this symbol is already open/unfilled.")
                    else:
                        # Re-check cash right before spending it (not the
                        # earlier starting_cash snapshot), in case an earlier
                        # ticker in this same loop already spent some of it.
                        cash_now = broker.get_cash()
                        budget = compute_buy_budget(per_ticker_budget, args.max_notional)
                        notional = min(budget, cash_now)
                        if notional < 1.0:
                            # Too little cash left to place a meaningful order.
                            print(f"[{ticker}] Not enough cash to buy; skipping.")
                            notional = None
                        else:
                            order = broker.buy_notional(symbol.alpaca, notional, is_crypto=symbol.is_crypto)
                            filled, filled_qty, filled_avg_price = poll_for_fill(broker, order)
                            if filled:
                                # Use the real fill price, not the decision-time
                                # market price - that's what realized P&L should
                                # actually be computed from later.
                                fill_price = filled_avg_price
                                print(f"[{ticker}] BUY filled: {filled_qty} @ ${filled_avg_price:.6f}.")
                            else:
                                fill_note = "Fill not confirmed within the polling window at log time - price/qty shown are decision-time estimates, not a confirmed fill."
                                print(f"[{ticker}] Submitted BUY order for ${notional:.2f} (fill not yet confirmed).")
                            executed = True
                elif action == "SELL":
                    order = broker.close_position(symbol.alpaca)
                    filled, filled_qty, filled_avg_price = poll_for_fill(broker, order)
                    if filled:
                        fill_price = filled_avg_price
                        print(f"[{ticker}] SELL filled: {filled_qty} @ ${filled_avg_price:.6f}.")
                    else:
                        fill_note = "Fill not confirmed within the polling window at log time - price/qty shown are decision-time estimates, not a confirmed fill."
                        print(f"[{ticker}] Submitted order to close position (fill not yet confirmed).")
                    executed = True
            elif action != "HOLD":
                # A real BUY/SELL signal fired, but --execute wasn't passed -
                # report what would have happened without actually doing it.
                print(f"[{ticker}] Dry run (pass --execute to actually place this order).")

            # Only real decisions get a row - HOLD is the overwhelming majority
            # of runs (especially on the 5-minute crypto schedule) and isn't
            # informative enough to justify a permanent, git-committed row every
            # single time. Full per-run detail, including HOLDs, is still
            # visible in that run's GitHub Actions console log if you need it.
            if action != "HOLD":
                log_trade({
                    "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                    "mode": mode,
                    "asset_class": kind,
                    "ticker": ticker,
                    "strategy": args.strategy,
                    "action": action,
                    # 2 decimals rounds sub-$1 assets (e.g. DOGE at $0.07) down to
                    # nothing - price_usd and avg_entry_price_usd need enough
                    # precision to tell entry and exit price apart, since that
                    # difference is exactly what realized P&L is computed from.
                    "price_usd": f"{fill_price:.6f}",
                    "notional_usd": f"{notional:.2f}" if notional is not None else "",
                    "position_qty_before": decision["current_qty"],
                    "avg_entry_price_usd": f"{decision['entry_price']:.6f}" if decision["entry_price"] else "",
                    "unrealized_gain_pct": f"{decision['gain_pct'] * 100:.2f}" if decision["gain_pct"] is not None else "",
                    "order_placed": executed,
                    "notes": fill_note,
                })
        except Exception as e:
            # Same reasoning as the decide() loop above - one ticker's
            # order placement or logging failing shouldn't stop the rest
            # of this run's tickers from being processed.
            print(f"[{ticker}] ERROR while executing/logging: {type(e).__name__}: {e}")

    # Always log account-level equity/cash at the end of every run
    # (subject to the "only if it changed" dedup inside log_equity above),
    # regardless of whether any individual ticker traded this time.
    # Same reasoning as the try/except above - don't let a transient
    # account-endpoint failure here surface as an unhandled crash after
    # everything else in this run already succeeded.
    try:
        log_equity({
            "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "mode": mode,
            "portfolio_value_usd": f"{broker.get_equity():.2f}",
            "cash_usd": f"{broker.get_cash():.2f}",
        })
    except Exception as e:
        print(f"ERROR logging final account equity: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
