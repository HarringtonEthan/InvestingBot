"""
Thin wrapper around the Alpaca trading API.

Defaults hard to paper trading (fake money, real live prices) and refuses
to touch a live account unless ALPACA_BASE_URL is explicitly overridden to
Alpaca's live endpoint AND the caller passes allow_live=True. This is a
deliberate double lock - one flag alone isn't enough to place a real order.
"""

from __future__ import annotations

import os

from alpaca.common.exceptions import APIError
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import GetOrdersRequest, MarketOrderRequest

PAPER_BASE_URL = "https://paper-api.alpaca.markets"
LIVE_BASE_URL = "https://api.alpaca.markets"


class Broker:
    def __init__(self, allow_live: bool = False):
        api_key = os.environ.get("ALPACA_API_KEY")
        secret_key = os.environ.get("ALPACA_SECRET_KEY")
        if not api_key or not secret_key:
            raise RuntimeError(
                "Set ALPACA_API_KEY and ALPACA_SECRET_KEY (see .env.example) "
                "before running live_trade.py."
            )

        base_url = os.environ.get("ALPACA_BASE_URL", PAPER_BASE_URL)
        self.is_paper = base_url != LIVE_BASE_URL

        if not self.is_paper and not allow_live:
            raise RuntimeError(
                "ALPACA_BASE_URL is set to Alpaca's LIVE endpoint, but live "
                "trading was not explicitly confirmed. Refusing to start. "
                "Pass --i-understand-this-is-live to live_trade.py if this "
                "is really what you want."
            )

        self.client = TradingClient(api_key, secret_key, paper=self.is_paper)

    def get_cash(self) -> float:
        account = self.client.get_account()
        return float(account.cash)

    def get_equity(self) -> float:
        account = self.client.get_account()
        return float(account.equity)

    @staticmethod
    def _position_symbol(symbol: str) -> str:
        # alpaca-py builds position/close-position URLs by plain string
        # concatenation (base_url + "/positions/" + symbol) with no
        # URL-encoding. Crypto symbols like "DOGE/USD" contain a literal
        # "/", which turns "/positions/DOGE/USD" into a 3-segment path
        # instead of the 2-segment one Alpaca's API expects - the request
        # 404s, and the caller's `except APIError` silently reports "no
        # position" even when a real one exists. Order placement (a POST
        # body field, not a URL path) is unaffected and still wants the
        # slash form - only these per-symbol lookups need it stripped.
        return symbol.replace("/", "")

    def get_position_qty(self, symbol: str) -> float:
        try:
            pos = self.client.get_open_position(self._position_symbol(symbol))
            return float(pos.qty)
        except APIError:
            return 0.0

    def get_position_avg_entry_price(self, symbol: str) -> float | None:
        """Your actual real cost basis for an open position, or None if you don't hold one."""
        try:
            pos = self.client.get_open_position(self._position_symbol(symbol))
            return float(pos.avg_entry_price)
        except APIError:
            return None

    def has_open_order(self, symbol: str) -> bool:
        """
        True if there's already an unfilled order sitting out there for this
        symbol - checked before placing a new one, so a fresh BUY signal
        doesn't stack another order on top of one still working (e.g. a DAY
        order submitted after market close, queued for the next session,
        that a later run has no other way of knowing about - decide() only
        ever checks *filled* position size, not pending orders).
        """
        request = GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol])
        orders = self.client.get_orders(filter=request)
        return len(orders) > 0

    def buy_notional(self, symbol: str, notional: float, is_crypto: bool = False):
        # Crypto orders on Alpaca don't support DAY (there's no market
        # close to expire at); they require GTC instead.
        tif = TimeInForce.GTC if is_crypto else TimeInForce.DAY
        order = MarketOrderRequest(
            symbol=symbol,
            notional=round(notional, 2),
            side=OrderSide.BUY,
            time_in_force=tif,
        )
        return self.client.submit_order(order)

    def close_position(self, symbol: str):
        return self.client.close_position(self._position_symbol(symbol))
