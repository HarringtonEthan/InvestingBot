"""
Run one automated trading decision, for one or more tickers, against an
Alpaca account (paper by default) and, if a position needs to change,
place the order.

Meant to be run on a schedule via cron / Task Scheduler / GitHub Actions -
see README.md "Automated paper trading" section for setup. Each run is
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

from __future__ import annotations

import argparse
import csv
import datetime as dt
import math
from pathlib import Path

from dotenv import load_dotenv

from src.alpaca_data import get_crypto_bars
from src.broker import Broker
from src.data import get_price_data
from src.features import add_features
from src.model import train_model
from src.model_store import load_model as load_saved_model
from src.strategies import bollinger_breakout, ml_filtered_dip_buy, rule_based_dip_buy
from src.symbols import resolve_symbol

TRADE_LOG_PATH = Path("logs/trade_log.csv")
TRADE_LOG_FIELDS = [
    "timestamp_utc", "mode", "asset_class", "ticker", "strategy",
    "action", "price_usd", "notional_usd", "position_qty_before",
    "avg_entry_price_usd", "unrealized_gain_pct", "order_placed",
]

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
        series = rule_based_dip_buy(df, dip_threshold=args.dip_threshold)
    elif strategy == "ml_filtered":
        saved = load_saved_model(args.model_path) if args.model_path else None
        if saved is not None:
            model, threshold, meta = saved
            print(f"[ml_filtered] Using saved model from {args.model_path} "
                  f"(trained {meta.get('trained_at', '?')} on {meta.get('tickers', '?')})")
        else:
            print(f"[ml_filtered] No saved model at {args.model_path!r} - training one inline "
                  f"from just this run's data instead (won't persist between runs). Run "
                  f"train_stock_model.py on a schedule to avoid this - see README.md.")
            model, threshold, _ = train_model(df)
        series = ml_filtered_dip_buy(df, model, threshold, dip_threshold=args.dip_threshold)
    elif strategy == "bollinger_breakout":
        series = bollinger_breakout(
            df, bb_window=args.bb_window, bb_std=args.bb_std, trend_window=args.trend_window,
        )
    else:
        raise ValueError(f"unknown strategy: {strategy}")
    return float(series.iloc[-1])


def _append_row(path: Path, fieldnames: list[str], row: dict):
    # fieldnames is always the fixed module-level list above, never derived
    # from row.keys() - a prior version did that, and once the row shape
    # changed after the file (and its header) already existed, every
    # subsequent row silently drifted out of alignment with its own header.
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
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


def decide(ticker: str, args, broker: Broker):
    """Returns a dict describing the decision for one ticker, or None if data was unusable."""
    symbol = resolve_symbol(ticker)
    lookback_days = args.lookback_days or DEFAULT_LOOKBACK_DAYS.get(args.interval, 30)

    if symbol.is_crypto:
        # Alpaca's own crypto feed, not Yahoo Finance: Yahoo's intraday
        # crypto bars can silently go stale for hours without erroring,
        # which is worse than a hard failure. Alpaca is also the actual
        # execution venue, so "current price" means what it says.
        try:
            raw = get_crypto_bars(symbol.alpaca, args.interval, lookback_days)
        except Exception as e:
            print(f"[{ticker}] SKIPPED: {e}")
            return None
    else:
        end = dt.date.today()
        start = end - dt.timedelta(days=lookback_days)
        raw, is_synthetic = get_price_data(symbol.yfinance, start.isoformat(), end.isoformat(), interval=args.interval)
        if is_synthetic:
            print(f"[{ticker}] SKIPPED: only synthetic fallback data was available "
                  f"(no real network access to Yahoo Finance from here).")
            return None

    df = add_features(raw)
    last_price = float(df["Close"].iloc[-1])
    last_date = df.index[-1]

    current_qty = broker.get_position_qty(symbol.alpaca)
    currently_holding = current_qty > 0

    entry_price = None
    gain_pct = None

    if args.strategy == "day_trading":
        pct_below = float(df["pct_below_sma20"].iloc[-1])
        if currently_holding:
            entry_price = broker.get_position_avg_entry_price(symbol.alpaca)
            if entry_price:
                gain_pct = last_price / entry_price - 1.0
                if gain_pct >= args.profit_target or gain_pct <= -args.stop_loss:
                    action = "SELL"
                else:
                    action = "HOLD"
            else:
                action = "HOLD"
        elif not math.isnan(pct_below) and pct_below <= args.dip_threshold:
            action = "BUY"
        else:
            action = "HOLD"
        target_position = 1.0 if (action == "BUY" or (action == "HOLD" and currently_holding)) else 0.0
    else:
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
                         help="day_trading: buy when price is this fraction below its rolling average, e.g. -0.02 = 2%% dip")
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
    parser.add_argument("--execute", action="store_true", help="actually submit orders; without this, dry-run only")
    parser.add_argument("--i-understand-this-is-live", action="store_true", dest="allow_live")
    args = parser.parse_args()

    load_dotenv()

    broker = Broker(allow_live=args.allow_live)
    mode = "PAPER" if broker.is_paper else "LIVE"

    tickers = args.ticker
    decisions = []
    for ticker in tickers:
        decision = decide(ticker, args, broker)
        if decision is not None:
            decisions.append(decision)

    # Split whatever cash is available evenly across tickers being watched
    # this run, so several simultaneous BUY signals don't let the first
    # one spend the whole account.
    starting_cash = broker.get_cash()
    per_ticker_budget = starting_cash / len(tickers) if tickers else 0.0

    for decision in decisions:
        ticker = decision["ticker"]
        symbol = decision["symbol"]
        action = decision["action"]

        kind = "crypto" if symbol.is_crypto else "stock"
        gain_str = f"  unrealized={decision['gain_pct']:+.2%}" if decision["gain_pct"] is not None else ""
        print(f"[{mode}] {ticker} ({kind}) as of {decision['last_date']}: price=${decision['last_price']:.2f}  "
              f"strategy={args.strategy}  current_qty={decision['current_qty']}{gain_str}  -> {action}")

        executed = False
        notional = None
        if action != "HOLD" and args.execute:
            if action == "BUY":
                if broker.has_open_order(symbol.alpaca):
                    print(f"[{ticker}] Skipping BUY - an order for this symbol is already open/unfilled.")
                else:
                    cash_now = broker.get_cash()
                    budget = min(per_ticker_budget, args.max_notional) if args.max_notional else per_ticker_budget
                    notional = min(budget, cash_now)
                    if notional < 1.0:
                        print(f"[{ticker}] Not enough cash to buy; skipping.")
                        notional = None
                    else:
                        broker.buy_notional(symbol.alpaca, notional, is_crypto=symbol.is_crypto)
                        print(f"[{ticker}] Submitted BUY order for ${notional:.2f}.")
                        executed = True
            elif action == "SELL":
                broker.close_position(symbol.alpaca)
                print(f"[{ticker}] Submitted order to close position.")
                executed = True
        elif action != "HOLD":
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
                "price_usd": f"{decision['last_price']:.6f}",
                "notional_usd": f"{notional:.2f}" if notional is not None else "",
                "position_qty_before": decision["current_qty"],
                "avg_entry_price_usd": f"{decision['entry_price']:.6f}" if decision["entry_price"] else "",
                "unrealized_gain_pct": f"{decision['gain_pct'] * 100:.2f}" if decision["gain_pct"] is not None else "",
                "order_placed": executed,
            })

    log_equity({
        "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "mode": mode,
        "portfolio_value_usd": f"{broker.get_equity():.2f}",
        "cash_usd": f"{broker.get_cash():.2f}",
    })


if __name__ == "__main__":
    main()
