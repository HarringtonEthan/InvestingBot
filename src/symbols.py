"""
Resolves a user-supplied ticker into the two different symbol formats
this project needs, and figures out whether it's a stock or crypto:

  - Yahoo Finance (price data) wants "BTC-USD"
  - Alpaca (order placement) wants "BTC/USD"

Accepts any of: a bare crypto base ("BTC"), Yahoo-style ("BTC-USD"), or
Alpaca-style ("BTC/USD"). Anything not recognized as crypto is treated as
a stock/ETF ticker (Yahoo and Alpaca use the same format for those, e.g.
"AAPL").
"""

# Lets type hints like "-> Symbol" refer to the Symbol class below even
# though Python is still in the middle of reading this file top to bottom.
from __future__ import annotations

# dataclass is a shortcut for writing a small class that just holds a few
# named values (like Symbol below) without hand-writing __init__ etc.
from dataclasses import dataclass

# Common, liquid pairs available on both Yahoo Finance and Alpaca's crypto
# API. Not exhaustive - if you want a coin that isn't listed here, pass it
# already in "XXX-USD" or "XXX/USD" form and it'll still be recognized as
# crypto.
# A set (curly braces, no key:value pairs) - fast "is this ticker in here?"
# lookups, and order doesn't matter since we never loop over it in order.
KNOWN_CRYPTO_BASES = {
    "BTC", "ETH", "SOL", "DOGE", "LTC", "AVAX", "LINK", "UNI",
    "AAVE", "BCH", "SHIB", "XRP", "DOT", "MATIC",
}


# frozen=True means once a Symbol is created its fields can't be changed -
# appropriate here since a resolved symbol shouldn't mutate after the fact.
@dataclass(frozen=True)
class Symbol:
    yfinance: str    # the format to hand to Yahoo Finance, e.g. "BTC-USD"
    alpaca: str      # the format to hand to Alpaca, e.g. "BTC/USD"
    is_crypto: bool  # True if this ticker was recognized as crypto, False for stocks/ETFs


def resolve_symbol(ticker: str) -> Symbol:
    # Normalize whatever the caller typed: trim stray spaces, force
    # uppercase, so "btc " and "BTC" and " Btc" all resolve the same way.
    t = ticker.strip().upper()

    # Case 1: already in Alpaca's "BASE/QUOTE" form, e.g. "BTC/USD".
    if "/" in t:
        # Everything before the "/" - e.g. "BTC" out of "BTC/USD".
        base = t.split("/")[0]
        # Yahoo wants a dash instead of a slash; Alpaca's format is already
        # exactly what was passed in, so reuse it as-is. Assumed crypto,
        # since only crypto pairs use this slash notation in this project.
        return Symbol(yfinance=t.replace("/", "-"), alpaca=t, is_crypto=True)

    # Case 2: already in Yahoo's "BASE-USD" form, e.g. "BTC-USD".
    if t.endswith("-USD"):
        # Strip the trailing "-USD" (4 characters) to get just "BTC".
        base = t[:-4]
        # Yahoo's format is already what was passed in; build Alpaca's
        # slash form from the extracted base.
        return Symbol(yfinance=t, alpaca=f"{base}/USD", is_crypto=True)

    # Case 3: a bare base symbol, e.g. "BTC" - check it against the known
    # crypto list above.
    if t in KNOWN_CRYPTO_BASES:
        # Build both formats from scratch since neither was supplied.
        return Symbol(yfinance=f"{t}-USD", alpaca=f"{t}/USD", is_crypto=True)

    # Fallback: not recognized as crypto in any form, so treat it as a
    # stock/ETF ticker - Yahoo and Alpaca use the identical format for
    # those (e.g. "AAPL"), so the same string works for both fields.
    return Symbol(yfinance=t, alpaca=t, is_crypto=False)
