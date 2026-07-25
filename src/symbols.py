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

from __future__ import annotations

from dataclasses import dataclass

# Common, liquid pairs available on both Yahoo Finance and Alpaca's crypto
# API. Not exhaustive - if you want a coin that isn't listed here, pass it
# already in "XXX-USD" or "XXX/USD" form and it'll still be recognized as
# crypto.
KNOWN_CRYPTO_BASES = {
    "BTC", "ETH", "SOL", "DOGE", "LTC", "AVAX", "LINK", "UNI",
    "AAVE", "BCH", "SHIB", "XRP", "DOT", "MATIC",
}


@dataclass(frozen=True)
class Symbol:
    yfinance: str
    alpaca: str
    is_crypto: bool


def resolve_symbol(ticker: str) -> Symbol:
    t = ticker.strip().upper()

    if "/" in t:
        base = t.split("/")[0]
        return Symbol(yfinance=t.replace("/", "-"), alpaca=t, is_crypto=True)

    if t.endswith("-USD"):
        base = t[:-4]
        return Symbol(yfinance=t, alpaca=f"{base}/USD", is_crypto=True)

    if t in KNOWN_CRYPTO_BASES:
        return Symbol(yfinance=f"{t}-USD", alpaca=f"{t}/USD", is_crypto=True)

    return Symbol(yfinance=t, alpaca=t, is_crypto=False)
