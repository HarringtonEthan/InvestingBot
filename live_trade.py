"""
Run one automated trading decision against an Alpaca account (paper by
default) and, if the position needs to change, place the order.

Meant to be run on a schedule (e.g. once a day, shortly before market
close) via cron / Task Scheduler - see README.md "Automated paper
trading" section for setup. Each run is stateless: it re-derives today's
buy/sell/hold decision from full price history and your *actual* broker
position, so it's safe to run it manually as many times as you want to
check what it would do.

Safety defaults:
  - Points at Alpaca's PAPER endpoint unless ALPACA_BASE_URL is changed.
  - Refuses to submit real orders unless --execute is passed; without it,
    it prints what it *would* do and stops.
  - Refuses to touch a live account at all unless you also pass
    --i-understand-this-is-live (on top of changing ALPACA_BASE_URL).
  - Aborts instead of trading on synthetic/fallback data.
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", default="SPY")
    parser.add_argument("--strategy", choices=["rule_based", "ml_filtered"], default="rule_based")
    parser.add_argument("--lookback-days", type=int, default=365 * 5, help="history to pull for indicators/model")
    parser.add_argument("--max-notional", type=float, default=None, help="cap $ amount per buy; default = all available cash")
    parser.add_argument("--execute", action="store_true", help="actually submit orders; without this, dry-run only")
    parser.add_argument("--i-understand-this-is-live", action="store_true", dest="allow_live")
    args = parser.parse_args()

    load_dotenv()

    end = dt.date.today()
    start = end - dt.timedelta(days=args.lookback_days)
    raw, is_synthetic = get_price_data(args.ticker, start.isoformat(), end.isoformat())
    if is_synthetic:
        raise SystemExit(
            "Live/paper trading requires real market data, but only the synthetic "
            "fallback was available (no network access to Yahoo Finance from here). "
            "Run this on a machine with normal internet access."
        )

    df = add_features(raw)
    last_price = float(df["Close"].iloc[-1])
    last_date = df.index[-1].date()

    target_position = get_target_position(df, args.strategy)

    broker = Broker(allow_live=args.allow_live)
    current_qty = broker.get_position_qty(args.ticker)
    currently_holding = current_qty > 0

    if target_position >= 1.0 and not currently_holding:
        action = "BUY"
    elif target_position <= 0.0 and currently_holding:
        action = "SELL"
    else:
        action = "HOLD"

    mode = "PAPER" if broker.is_paper else "LIVE"
    print(f"[{mode}] {args.ticker} as of {last_date}: price=${last_price:.2f}  "
          f"strategy={args.strategy}  target_position={target_position:.0f}  "
          f"current_qty={current_qty}  -> {action}")

    executed = False
    if action != "HOLD" and args.execute:
        if action == "BUY":
            cash = broker.get_cash()
            notional = min(cash, args.max_notional) if args.max_notional else cash
            if notional < 1.0:
                print("Not enough cash to buy; skipping.")
            else:
                broker.buy_notional(args.ticker, notional)
                print(f"Submitted BUY order for ${notional:.2f} of {args.ticker}.")
                executed = True
        elif action == "SELL":
            broker.close_position(args.ticker)
            print(f"Submitted order to close {args.ticker} position.")
            executed = True
    elif action != "HOLD":
        print("Dry run (pass --execute to actually place this order).")

    log_run({
        "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
        "ticker": args.ticker,
        "strategy": args.strategy,
        "price": f"{last_price:.2f}",
        "target_position": target_position,
        "current_qty_before": current_qty,
        "action": action,
        "executed": executed,
    })


if __name__ == "__main__":
    main()
