"""
Periodic retraining for the stock ML dip-filter (`live_trade.py --strategy
ml_filtered`).

Unlike the inline `train_model()` call used elsewhere in this repo - which
fits a brand-new model from scratch on every single invocation and then
discards it - this script is meant to be the ONLY place the *live* stock
model actually gets (re)trained. It pools recent data across multiple
tickers into one model (so it isn't overfit to a single stock's quirks),
saves it to disk (`models/stock_model.pkl`), and logs the retrain event.
`live_trade.py` then loads that saved model for every live decision until
this script runs again and replaces it - that's what makes it "learn" in
an ongoing sense rather than resetting every run.

Run this on a schedule (see .github/workflows/retrain-stock-model.yml) -
weekly is a reasonable starting cadence for daily-bar stock data. GitHub's
own `schedule:` trigger has been unreliable in this project (see
README.md "Current live status"); point an external scheduler (e.g.
cron-job.org) at that workflow's `workflow_dispatch` endpoint the same way
it's already wired up for the live crypto workflow.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
from pathlib import Path

from src.data import get_price_data
from src.features import add_features
from src.model import train_model_multi
from src.model_store import save_model

LOG_PATH = Path("logs/retrain_log.csv")


def log_retrain(row: dict):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    is_new = not LOG_PATH.exists()
    with LOG_PATH.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if is_new:
            writer.writeheader()
        writer.writerow(row)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", nargs="+", default=["SPY", "AAPL", "QQQ"],
                         help="tickers to pool into one training set, e.g. --ticker SPY AAPL QQQ")
    parser.add_argument("--lookback-days", type=int, default=730,
                         help="how much daily history to train on (default ~2 years)")
    parser.add_argument("--horizon", type=int, default=10,
                         help="label horizon in trading days (see src/model.py build_labels)")
    parser.add_argument("--bounce-pct", type=float, default=0.03,
                         help="label threshold: price must rise at least this much within --horizon days")
    parser.add_argument("--out", default="models/stock_model.pkl")
    args = parser.parse_args()

    end = dt.date.today()
    start = end - dt.timedelta(days=args.lookback_days)

    print(f"Training on {len(args.ticker)} tickers, {start} -> {end}...")
    train_dfs = {}
    for ticker in args.ticker:
        raw, is_synthetic = get_price_data(ticker, start.isoformat(), end.isoformat(), interval="1d")
        if is_synthetic:
            print(f"  {ticker}: SKIPPED (only synthetic fallback data available - no real network access)")
            continue
        train_dfs[ticker] = add_features(raw)
        print(f"  {ticker}: {len(train_dfs[ticker])} rows")

    if not train_dfs:
        raise SystemExit("\nNo usable ticker data - this needs real network access to Yahoo Finance.")

    model, threshold, train_scores = train_model_multi(
        train_dfs, horizon=args.horizon, bounce_pct=args.bounce_pct,
    )

    meta = {
        "trained_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "tickers": list(train_dfs.keys()),
        "lookback_days": args.lookback_days,
        "horizon": args.horizon,
        "bounce_pct": args.bounce_pct,
        "train_rows": int(sum(len(df) for df in train_dfs.values())),
    }
    save_model(model, threshold, meta, args.out)

    print(f"\nTrained on {meta['train_rows']} pooled rows across {len(train_dfs)} tickers.")
    print(f"Train-set predicted bounce-probability range: [{train_scores.min():.3f}, {train_scores.max():.3f}]")
    print(f"Calibrated threshold (75th pct of train scores): {threshold:.3f}")
    print(f"Saved model to {args.out}")

    log_retrain({
        "timestamp": meta["trained_at"],
        "tickers": ";".join(meta["tickers"]),
        "lookback_days": args.lookback_days,
        "train_rows": meta["train_rows"],
        "threshold": f"{threshold:.4f}",
    })


if __name__ == "__main__":
    main()
