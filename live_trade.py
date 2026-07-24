"""
Run one automated trading decision, for one or more tickers, against an
Alpaca account (paper by default) and, if a position needs to change,
place the order.

Meant to be run on a schedule (e.g. once a day, shortly before market
close) via cron / Task Scheduler - see README.md "Automated paper
trading" section for setup. Each run is stateless: it re-derives that
day's buy/sell/hold decision from full price history and your *actual*
broker position for each ticker, so it's safe to run it manually as many
times as you want to check what it would do.

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
from pathlib import Path

from dotenv import load_dotenv

from src.broker import Broker
from src.data import get_price_data
from src.features import add_features
from src.model import train_model
from src.strategies import ml_filtered_dip_buy, rule_based_dip_buy

LOG_PATH = Path("logs/trade_log.csv")


def get_target_position(df, strategy: str) -> float:
    if strategy == "rule_based":
        series = rule_based_dip_buy(df)
    elif strategy == "ml_filtered":
        model, threshold, _ = train_model(df)
        series = ml_filtered_dip_buy(df, model, threshold)
    else:
        raise ValueError(f"unknown strategy: {strategy}")
    return float(series.iloc[-1])


def log_run(row: dict):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    is_new = not LOG_PATH.exists()
    with LOG_PATH.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if is_new:
            writer.writeheader()
        writer.writerow(row)


def decide(ticker: str, strategy: str, start: str, end: str, broker: Broker):
    """Returns a dict describing the decision for one ticker, or None if data was unusable."""
    raw, is_synthetic = get_price_data(ticker, start, end)
    if is_synthetic:
        print(f"[{ticker}] SKIPPED: only synthetic fallback data was available "
              f"(no real network access to Yahoo Finance from here).")
        return None

    df = add_features(raw)
    last_price = float(df["Close"].iloc[-1])
    last_date = df.index[-1].date()

    target_position = get_target_position(df, strategy)

    current_qty = broker.get_position_qty(ticker)
    currently_holding = current_qty > 0

    if target_position >= 1.0 and not currently_holding:
        action = "BUY"
    elif target_position <= 0.0 and currently_holding:
        action = "SELL"
    else:
        action = "HOLD"

    return {
        "ticker": ticker,
        "last_price": last_price,
        "last_date": last_date,
        "target_position": target_position,
        "current_qty": current_qty,
        "action": action,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", nargs="+", default=["SPY"],
                         help="one or more tickers, space-separated, e.g. --ticker SPY AAPL QQQ")
    parser.add_argument("--strategy", choices=["rule_based", "ml_filtered"], default="rule_based")
    parser.add_argument("--lookback-days", type=int, default=365 * 5, help="history to pull for indicators/model")
    parser.add_argument("--max-notional", type=float, default=None,
                         help="cap $ amount per buy; default = an even split of available cash across tickers")
    parser.add_argument("--execute", action="store_true", help="actually submit orders; without this, dry-run only")
    parser.add_argument("--i-understand-this-is-live", action="store_true", dest="allow_live")
    args = parser.parse_args()

    load_dotenv()

    end = dt.date.today()
    start = end - dt.timedelta(days=args.lookback_days)

    broker = Broker(allow_live=args.allow_live)
    mode = "PAPER" if broker.is_paper else "LIVE"

    tickers = args.ticker
    decisions = []
    for ticker in tickers:
        decision = decide(ticker, args.strategy, start.isoformat(), end.isoformat(), broker)
        if decision is not None:
            decisions.append(decision)

    # Split whatever cash is available evenly across tickers being watched
    # this run, so several simultaneous BUY signals don't let the first
    # one spend the whole account.
    starting_cash = broker.get_cash()
    per_ticker_budget = starting_cash / len(tickers) if tickers else 0.0

    for decision in decisions:
        ticker = decision["ticker"]
        action = decision["action"]

        print(f"[{mode}] {ticker} as of {decision['last_date']}: price=${decision['last_price']:.2f}  "
              f"strategy={args.strategy}  target_position={decision['target_position']:.0f}  "
              f"current_qty={decision['current_qty']}  -> {action}")

        executed = False
        if action != "HOLD" and args.execute:
            if action == "BUY":
                cash_now = broker.get_cash()
                budget = min(per_ticker_budget, args.max_notional) if args.max_notional else per_ticker_budget
                notional = min(budget, cash_now)
                if notional < 1.0:
                    print(f"[{ticker}] Not enough cash to buy; skipping.")
                else:
                    broker.buy_notional(ticker, notional)
                    print(f"[{ticker}] Submitted BUY order for ${notional:.2f}.")
                    executed = True
            elif action == "SELL":
                broker.close_position(ticker)
                print(f"[{ticker}] Submitted order to close position.")
                executed = True
        elif action != "HOLD":
            print(f"[{ticker}] Dry run (pass --execute to actually place this order).")

        log_run({
            "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
            "mode": mode,
            "ticker": ticker,
            "strategy": args.strategy,
            "price": f"{decision['last_price']:.2f}",
            "target_position": decision["target_position"],
            "current_qty_before": decision["current_qty"],
            "action": action,
            "executed": executed,
        })


if __name__ == "__main__":
    main()
