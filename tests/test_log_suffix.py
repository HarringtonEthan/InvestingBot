"""
Tests for live_trade.py's --log-suffix behavior: the crypto and stock
workflows each pass a different suffix so they write to separate files
(logs/trade_log_crypto.csv vs logs/trade_log_stocks.csv, same for
equity) - two different workflows can then never race to commit the
same file, on top of the .gitattributes merge=union fix for anything
that still does share a log (e.g. manual local runs with no suffix).
"""

import live_trade


def test_log_suffix_produces_separate_filenames(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    # Mirrors exactly what main() does with a non-empty --log-suffix -
    # via monkeypatch (not a bare module-attribute assignment) so it's
    # automatically undone after this test, not leaked into the next one.
    suffix = "_crypto"
    monkeypatch.setattr(live_trade, "TRADE_LOG_PATH", live_trade.Path(f"logs/trade_log{suffix}.csv"))
    monkeypatch.setattr(live_trade, "EQUITY_LOG_PATH", live_trade.Path(f"logs/equity_log{suffix}.csv"))

    live_trade.log_trade({field: "" for field in live_trade.TRADE_LOG_FIELDS})
    live_trade.log_equity({
        "timestamp_utc": "2026-01-01T00:00:00+00:00",
        "mode": "PAPER",
        "portfolio_value_usd": "100000.00",
        "cash_usd": "100000.00",
    })

    assert (tmp_path / "logs" / "trade_log_crypto.csv").exists()
    assert (tmp_path / "logs" / "equity_log_crypto.csv").exists()
    assert not (tmp_path / "logs" / "trade_log.csv").exists()
    assert not (tmp_path / "logs" / "equity_log.csv").exists()


def test_no_log_suffix_keeps_the_plain_filenames(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(live_trade, "TRADE_LOG_PATH", live_trade.Path("logs/trade_log.csv"))
    monkeypatch.setattr(live_trade, "EQUITY_LOG_PATH", live_trade.Path("logs/equity_log.csv"))

    live_trade.log_trade({field: "" for field in live_trade.TRADE_LOG_FIELDS})

    assert (tmp_path / "logs" / "trade_log.csv").exists()
