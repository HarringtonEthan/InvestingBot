"""
Tests for the daily-loss circuit breaker in live_trade.py: new BUYs
should be blocked once the account is down enough from today's first
logged equity value, but the function must never block trading just
because no baseline exists yet (e.g. the very first run of the day).
"""

import datetime as dt

import pytest

import live_trade
from tests.fake_broker import FakeBroker


@pytest.fixture
def temp_equity_log(tmp_path, monkeypatch):
    # pytest's tmp_path gives each test its own throwaway directory,
    # auto-cleaned afterward - point live_trade's EQUITY_LOG_PATH at a
    # file in there instead of the real logs/equity_log.csv, so these
    # tests can never touch real account history.
    log_path = tmp_path / "equity_log.csv"
    monkeypatch.setattr(live_trade, "EQUITY_LOG_PATH", log_path)
    return log_path


def _write_equity_rows(path, rows):
    # Writes a fake equity_log.csv with exactly the rows a test wants,
    # in the same format live_trade.py's own log_equity() produces.
    import csv
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=live_trade.EQUITY_LOG_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def test_no_baseline_yet_today_does_not_block(temp_equity_log):
    # Log file doesn't exist at all yet - nothing to compare against.
    broker = FakeBroker(cash=95_000.0)
    assert live_trade.daily_loss_exceeded(broker, threshold_pct=0.05) is False


def test_small_loss_does_not_trip_breaker(temp_equity_log):
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    _write_equity_rows(temp_equity_log, [
        {"timestamp_utc": f"{today}T00:00:00+00:00", "mode": "PAPER", "portfolio_value_usd": "100000.00", "cash_usd": "100000.00"},
    ])
    broker = FakeBroker(cash=98_000.0)  # -2%, well under a 5% threshold
    assert live_trade.daily_loss_exceeded(broker, threshold_pct=0.05) is False


def test_large_loss_trips_breaker(temp_equity_log):
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    _write_equity_rows(temp_equity_log, [
        {"timestamp_utc": f"{today}T00:00:00+00:00", "mode": "PAPER", "portfolio_value_usd": "100000.00", "cash_usd": "100000.00"},
    ])
    broker = FakeBroker(cash=94_000.0)  # -6%, over a 5% threshold
    assert live_trade.daily_loss_exceeded(broker, threshold_pct=0.05) is True


def test_uses_first_row_of_today_not_yesterday(temp_equity_log):
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    yesterday = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).date().isoformat()
    _write_equity_rows(temp_equity_log, [
        {"timestamp_utc": f"{yesterday}T00:00:00+00:00", "mode": "PAPER", "portfolio_value_usd": "50000.00", "cash_usd": "50000.00"},
        {"timestamp_utc": f"{today}T00:00:00+00:00", "mode": "PAPER", "portfolio_value_usd": "100000.00", "cash_usd": "100000.00"},
    ])
    # Down 6% from today's actual start (100k), not from yesterday's
    # unrelated 50k value - must trip using the right baseline.
    broker = FakeBroker(cash=94_000.0)
    assert live_trade.daily_loss_exceeded(broker, threshold_pct=0.05) is True
