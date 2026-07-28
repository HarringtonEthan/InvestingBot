"""
Tests for live_trade.py's check_bars_freshness() and the real root cause
it was added to guard against: a live stock decision being silently
computed from a frozen/stale bars series.

The actual bug (confirmed live on 2026-07-28, see CHANGELOG.md) wasn't
Alpaca's data itself going stale - it was decide()'s own stock branch
passing `dt.date.today().isoformat()` (a bare calendar date, e.g.
"2026-07-28") as the `end` bound to get_price_data_smart(). pd.Timestamp()
turns a bare date into midnight UTC of that day, which is *hours before*
the moment a live run actually executes - so every live stock fetch's
own upper bound silently excluded the entire current trading session,
regardless of what the real time was. Fixed by passing a real timestamp
(dt.datetime.now(dt.timezone.utc)) instead. check_bars_freshness() is the
second, independent safety net: even with the correct `end` bound, a
returned series could still end up stale for some other reason (an
Alpaca outage, a market holiday) - the same guarantee get_crypto_bars()
already has, applied to stocks too.
"""

import datetime as dt

import pandas as pd
import pytest

from live_trade import check_bars_freshness, decide
from tests.fake_broker import FakeBroker


def test_raises_when_latest_bar_is_older_than_threshold():
    # 5m interval's staleness threshold is 15 minutes (see
    # src/alpaca_data.py's STALENESS_MINUTES) - 2 hours old is well past it.
    stale_ts = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2)
    with pytest.raises(RuntimeError, match="stale"):
        check_bars_freshness("AAPL", stale_ts, "5m")


def test_does_not_raise_when_latest_bar_is_fresh():
    fresh_ts = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)
    check_bars_freshness("AAPL", fresh_ts, "5m")  # must not raise


def test_handles_a_timezone_naive_timestamp():
    # pandas DatetimeIndex entries can come back tz-naive depending on how
    # they were constructed - must still be comparable against "now"
    # (also UTC) instead of raising a naive/aware TypeError.
    fresh_naive = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(minutes=1)
    check_bars_freshness("AAPL", fresh_naive, "5m")  # must not raise


def test_uses_a_longer_threshold_for_a_longer_interval():
    # A 1h-interval bar 90 minutes old is within that interval's own
    # (much more generous) threshold, even though it would fail the 5m
    # threshold above.
    ts = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=80)
    check_bars_freshness("AAPL", ts, "1h")  # must not raise


class _Args:
    strategy = "rule_based"
    interval = "5m"
    lookback_days = None
    dip_threshold = -0.02
    exit_threshold = 0.0
    rule_stop_loss = None
    rule_stop_cooldown = None


def test_decide_passes_a_real_timestamp_not_a_bare_date_as_end(monkeypatch):
    """
    Regression test for the actual root cause: decide()'s stock branch
    must ask get_price_data_smart() for bars up through the real current
    moment, not midnight UTC of today (which a bare `dt.date.today()`
    would silently produce, and did in production - see module docstring
    above).
    """
    captured = {}

    def fake_get_price_data_smart(ticker, start, end, interval="1d"):
        captured["start"] = start
        captured["end"] = end
        idx = pd.date_range(end="2026-07-28 18:00:00+00:00", periods=25, freq="5min", tz="UTC")
        df = pd.DataFrame({"Close": list(range(25))}, index=idx)
        return df, False, "alpaca"

    monkeypatch.setattr("live_trade.get_price_data_smart", fake_get_price_data_smart)

    decide("AAPL", _Args(), FakeBroker())

    # A bare calendar date string is exactly 10 characters (e.g.
    # "2026-07-28"); a real timestamp's isoformat() is always longer
    # (it includes a "T" and a time-of-day component).
    assert len(captured["end"]) > len("2026-07-28")
    assert "T" in captured["end"]


def test_decide_skips_stock_ticker_when_returned_bars_are_stale(monkeypatch):
    def fake_get_price_data_smart(ticker, start, end, interval="1d"):
        stale_idx = pd.date_range("2026-07-27 15:55:00+00:00", periods=25, freq="5min", tz="UTC")
        df = pd.DataFrame({"Close": list(range(25))}, index=stale_idx)
        return df, False, "alpaca"

    monkeypatch.setattr("live_trade.get_price_data_smart", fake_get_price_data_smart)

    result = decide("AAPL", _Args(), FakeBroker())
    assert result is None
