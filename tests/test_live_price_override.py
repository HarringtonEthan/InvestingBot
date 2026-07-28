"""
Tests for apply_live_price_override() in live_trade.py - patches just the
last row of an already-fetched bars series with a genuinely live trade
price, before add_features() computes rolling indicators from it. See
its docstring and decide()'s comment for why: live trading found that
even Alpaca's own free IEX historical-bars feed can sit several percent
away from Alpaca's real-time pricing at the exact same moment, so the
final "where is price right now" point shouldn't be trusted from the
bars series alone.
"""

import pandas as pd

from live_trade import apply_live_price_override


def _bars(closes):
    idx = pd.date_range("2026-07-27", periods=len(closes), freq="5min", tz="UTC")
    return pd.DataFrame({"Close": closes}, index=idx)


def test_overrides_only_the_last_close():
    raw = _bars([100.0, 101.0, 102.0])
    result = apply_live_price_override(raw, live_price=150.0)
    assert result["Close"].tolist() == [100.0, 101.0, 150.0]


def test_does_not_mutate_the_original_dataframe():
    raw = _bars([100.0, 101.0, 102.0])
    apply_live_price_override(raw, live_price=150.0)
    # The caller's own copy must be untouched - decide() may still want
    # to reference it, or a test/caller may reuse the same fixture.
    assert raw["Close"].iloc[-1] == 102.0


def test_index_and_length_are_unchanged():
    raw = _bars([100.0, 101.0, 102.0])
    result = apply_live_price_override(raw, live_price=150.0)
    assert len(result) == 3
    assert list(result.index) == list(raw.index)
