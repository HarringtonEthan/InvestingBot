"""
Tests for live_trade.py's compute_buy_budget() - specifically the
truthiness edge case that was previously wrong: --max-notional 0 (an
explicit, deliberate zero cap) used to be treated the same as
"--max-notional not passed at all" because Python's `if x:` treats 0
and None identically, silently falling back to the uncapped per-ticker
split instead of actually capping at $0.
"""

from live_trade import compute_buy_budget, compute_per_ticker_budget


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


# ---- compute_per_ticker_budget (the pre-cap sizing step) ----

def test_default_mode_is_even_split_across_tickers():
    assert compute_per_ticker_budget(starting_cash=90000.0, num_tickers=9, position_fraction=None) == 10000.0


def test_default_mode_zero_tickers_budgets_zero_not_dividebyzero():
    assert compute_per_ticker_budget(starting_cash=90000.0, num_tickers=0, position_fraction=None) == 0.0


def test_fraction_mode_ignores_ticker_count():
    # 0.2 of cash per buy regardless of how many tickers are watched -
    # the whole point of the flag is "same fraction on a $250 account
    # and a $100k one," not a per-ticker split.
    assert compute_per_ticker_budget(starting_cash=250.0, num_tickers=9, position_fraction=0.2) == 50.0
    assert compute_per_ticker_budget(starting_cash=100000.0, num_tickers=9, position_fraction=0.2) == 20000.0


def test_fraction_mode_still_capped_by_max_notional():
    # The two layers compose: fraction sizes the buy, --max-notional
    # still ceilings it.
    budget = compute_per_ticker_budget(starting_cash=100000.0, num_tickers=9, position_fraction=0.2)
    assert compute_buy_budget(per_ticker_budget=budget, max_notional=15000.0) == 15000.0
