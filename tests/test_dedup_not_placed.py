"""
Tests for live_trade.py's "not placed" log dedup: a real (non-HOLD)
signal that fires every single 5-minute run while its underlying
condition holds - most commonly a stock dip signal persisting for hours
purely because the market is closed - used to grow trade_log*.csv (and
the git history it's committed into) by one near-duplicate row every
run, for as long as that held. load_last_logged_rows/
is_duplicate_not_placed recognize when nothing has actually changed
since the last logged row for a ticker and skip logging it again.
"""

import csv

import live_trade


def _write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=live_trade.TRADE_LOG_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _row(**overrides):
    row = {field: "" for field in live_trade.TRADE_LOG_FIELDS}
    row.update({
        "ticker": "AAPL",
        "action": "BUY",
        "order_placed": "False",
        "notes": "Stock market was closed at decision time - order not submitted.",
    })
    row.update(overrides)
    return row


def test_load_last_logged_rows_empty_when_file_missing(tmp_path):
    result = live_trade.load_last_logged_rows(tmp_path / "does_not_exist.csv")
    assert result == {}


def test_load_last_logged_rows_keeps_most_recent_per_ticker(tmp_path):
    path = tmp_path / "trade_log.csv"
    _write_rows(path, [
        _row(ticker="AAPL", price_usd="320.00"),
        _row(ticker="QQQ", price_usd="680.00"),
        _row(ticker="AAPL", price_usd="325.00"),  # later row for AAPL - this one should win
    ])
    result = live_trade.load_last_logged_rows(path)
    assert result["AAPL"]["price_usd"] == "325.00"
    assert result["QQQ"]["price_usd"] == "680.00"


def test_is_duplicate_when_nothing_changed():
    last_row = _row()
    assert live_trade.is_duplicate_not_placed(
        last_row, "AAPL", "BUY", "Stock market was closed at decision time - order not submitted."
    ) is True


def test_not_duplicate_when_no_prior_row():
    assert live_trade.is_duplicate_not_placed(None, "AAPL", "BUY", "some note") is False


def test_not_duplicate_when_action_differs():
    last_row = _row(action="BUY")
    assert live_trade.is_duplicate_not_placed(last_row, "AAPL", "SELL", last_row["notes"]) is False


def test_not_duplicate_when_notes_differ():
    last_row = _row(notes="Stock market was closed at decision time - order not submitted.")
    assert live_trade.is_duplicate_not_placed(last_row, "AAPL", "BUY", "Skipping BUY - daily loss circuit breaker is active.") is False


def test_not_duplicate_when_prior_row_was_actually_placed():
    # order_placed True means a real order was submitted last time - a
    # fresh not-placed row now is never a duplicate of a genuine fill/
    # submission, regardless of matching action/notes text.
    last_row = _row(order_placed="True", notes="")
    assert live_trade.is_duplicate_not_placed(last_row, "AAPL", "BUY", "") is False


def test_not_duplicate_for_a_different_ticker():
    last_row = _row(ticker="QQQ")
    assert live_trade.is_duplicate_not_placed(last_row, "AAPL", "BUY", last_row["notes"]) is False
