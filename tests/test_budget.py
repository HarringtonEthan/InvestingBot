"""
Tests for live_trade.py's compute_buy_budget() - specifically the
truthiness edge case that was previously wrong: --max-notional 0 (an
explicit, deliberate zero cap) used to be treated the same as
"--max-notional not passed at all" because Python's `if x:` treats 0
and None identically, silently falling back to the uncapped per-ticker
split instead of actually capping at $0.
"""

from live_trade import compute_buy_budget


def test_no_cap_uses_full_per_ticker_budget():
    assert compute_buy_budget(per_ticker_budget=5000.0, max_notional=None) == 5000.0


def test_cap_below_budget_is_applied():
    assert compute_buy_budget(per_ticker_budget=11000.0, max_notional=2000.0) == 2000.0


def test_cap_above_budget_has_no_effect():
    # The cap is only ever a ceiling - it should never raise the budget
    # above what the even per-ticker split already allows.
    assert compute_buy_budget(per_ticker_budget=1000.0, max_notional=5000.0) == 1000.0


def test_explicit_zero_cap_is_respected_not_ignored():
    # This is the bug: an explicit 0 must mean "never buy," not "no cap
    # was given."
    assert compute_buy_budget(per_ticker_budget=5000.0, max_notional=0.0) == 0.0
