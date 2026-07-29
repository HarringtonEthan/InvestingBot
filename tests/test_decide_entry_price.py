"""
Regression test for a real production bug (confirmed live 2026-07-29,
see CHANGELOG): decide()'s cost-basis lookup (broker.get_position_avg_
entry_price) used to sit inside the `if args.strategy == "day_trading"`
branch, so a SELL under any other strategy (rule_based, ml_filtered -
the strategies actually running live) logged an empty
avg_entry_price_usd. That's not just unused at decision time - it's
permanently unrecoverable, since site_data.py can never compute a
realized P&L for that trade from a blank cost-basis field afterward
(and, until site_data.py's own defensive fix, crashed the whole
scheduled dashboard-update run trying to rank it against other trades).
"""

import datetime as dt

import pandas as pd
import pytest

from live_trade import decide
from tests.fake_broker import FakeBroker


class _Args:
    strategy = "rule_based"
    interval = "5m"
    lookback_days = None
    dip_threshold = -0.02
    exit_threshold = 0.0
    rule_stop_loss = None
    rule_stop_cooldown = None


def _fake_get_price_data_smart(ticker, start, end, interval="1d"):
    # Flat price series - plenty of rows for every rolling indicator
    # (sma50 etc.) to be fully populated by the last row, ending "now" so
    # check_bars_freshness() doesn't reject it as stale. The actual
    # BUY/SELL/HOLD outcome doesn't matter for this test; only that the
    # cost basis was fetched at all while a position is held.
    now = dt.datetime.now(dt.timezone.utc)
    idx = pd.date_range(end=now, periods=60, freq="5min")
    df = pd.DataFrame({"Close": [100.0] * 60}, index=idx)
    return df, False, "alpaca"


def test_decide_fetches_entry_price_for_rule_based_when_holding(monkeypatch):
    monkeypatch.setattr("live_trade.get_price_data_smart", _fake_get_price_data_smart)
    broker = FakeBroker()
    broker._positions["AAPL"] = (10.0, 150.0)  # currently holding, real cost basis $150

    result = decide("AAPL", _Args(), broker)

    assert result["entry_price"] == pytest.approx(150.0)


def test_decide_leaves_entry_price_none_when_flat(monkeypatch):
    monkeypatch.setattr("live_trade.get_price_data_smart", _fake_get_price_data_smart)
    broker = FakeBroker()  # no open position

    result = decide("AAPL", _Args(), broker)

    assert result["entry_price"] is None
