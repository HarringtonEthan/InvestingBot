"""
Thin wrapper around the Alpaca trading API.

Defaults hard to paper trading (fake money, real live prices) and refuses
to touch a live account unless ALPACA_BASE_URL is explicitly overridden to
Alpaca's live endpoint AND the caller passes allow_live=True. This is a
deliberate double lock - one flag alone isn't enough to place a real order.
"""

# Lets type hints work without issue in this Python version.
from __future__ import annotations

# For reading API credentials and the base URL out of environment variables.
import os

# The exception Alpaca's SDK raises on a failed API call (e.g. no position
# found, bad request) - caught below to distinguish "no position" from a
# real error.
from alpaca.common.exceptions import APIError
# The actual client class that talks to Alpaca's REST API.
from alpaca.trading.client import TradingClient
# Enums for order side (buy/sell), order status filters, and how long an
# order should remain active before it's cancelled automatically.
from alpaca.trading.enums import OrderSide, QueryOrderStatus, TimeInForce
# Request payload builders: one for listing orders with filters, one for
# submitting a new market order.
from alpaca.trading.requests import GetOrdersRequest, MarketOrderRequest

# Paper trading endpoint - fake money, real live market prices. This is
# the default this whole project runs against.
PAPER_BASE_URL = "https://paper-api.alpaca.markets"
# Real-money endpoint - only reachable via the explicit double lock below.
LIVE_BASE_URL = "https://api.alpaca.markets"


class Broker:
    def __init__(self, allow_live: bool = False):
        # Credentials are read from the environment, never hardcoded -
        # keeps secrets out of the source code and out of git history.
        api_key = os.environ.get("ALPACA_API_KEY")
        secret_key = os.environ.get("ALPACA_SECRET_KEY")
        if not api_key or not secret_key:
            # Fail immediately and clearly rather than letting a later,
            # more confusing authentication error surface from inside
            # the Alpaca SDK.
            raise RuntimeError(
                "Set ALPACA_API_KEY and ALPACA_SECRET_KEY (see .env.example) "
                "before running live_trade.py."
            )

        # Which endpoint to hit - defaults to paper trading if the
        # environment variable isn't set at all.
        base_url = os.environ.get("ALPACA_BASE_URL", PAPER_BASE_URL)
        # Paper mode unless the base URL is *exactly* the live endpoint -
        # any unrecognized value is treated as paper, the safe default.
        self.is_paper = base_url != LIVE_BASE_URL

        if not self.is_paper and not allow_live:
            # Second half of the double lock: even with the live URL
            # configured, refuse to proceed unless the caller explicitly
            # opted in via allow_live=True (wired to a CLI flag in
            # live_trade.py) - protects against accidentally trading
            # real money just because an environment variable got set wrong.
            raise RuntimeError(
                "ALPACA_BASE_URL is set to Alpaca's LIVE endpoint, but live "
                "trading was not explicitly confirmed. Refusing to start. "
                "Pass --i-understand-this-is-live to live_trade.py if this "
                "is really what you want."
            )

        # Build the actual SDK client; paper=self.is_paper tells it which
        # of Alpaca's two endpoints/environments to talk to.
        self.client = TradingClient(api_key, secret_key, paper=self.is_paper)

    def get_cash(self) -> float:
        # Free cash available in the account (not counting buying power
        # from margin, which this project doesn't use).
        account = self.client.get_account()
        return float(account.cash)

    def get_equity(self) -> float:
        # Total account value: cash plus the current market value of
        # every open position combined.
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
            # Ask Alpaca for the currently open position in this symbol
            # (using the slash-stripped form - see _position_symbol above).
            pos = self.client.get_open_position(self._position_symbol(symbol))
            return float(pos.qty)
        except APIError:
            # No open position (or the lookup failed) - treat as holding
            # zero rather than propagating the error up.
            return 0.0

    def get_position_avg_entry_price(self, symbol: str) -> float | None:
        """Your actual real cost basis for an open position, or None if you don't hold one."""
        try:
            pos = self.client.get_open_position(self._position_symbol(symbol))
            return float(pos.avg_entry_price)
        except APIError:
            # No position to have an entry price for.
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
        # Build a filter asking specifically for OPEN (unfilled/partially
        # filled, still working) orders on just this one symbol.
        request = GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol])
        orders = self.client.get_orders(filter=request)
        # Any result at all means there's already an order out there.
        return len(orders) > 0

    def buy_notional(self, symbol: str, notional: float, is_crypto: bool = False):
        # Crypto orders on Alpaca don't support DAY (there's no market
        # close to expire at); they require GTC instead.
        # GTC = "good 'til cancelled" (stays open indefinitely); DAY =
        # expires automatically at market close if unfilled.
        tif = TimeInForce.GTC if is_crypto else TimeInForce.DAY
        order = MarketOrderRequest(
            symbol=symbol,               # which asset to buy, in Alpaca's format (e.g. "BTC/USD" or "AAPL")
            notional=round(notional, 2),  # dollar amount to spend, rounded to whole cents
            side=OrderSide.BUY,           # this is a buy order, not a sell
            time_in_force=tif,            # how long the order should stay open if not immediately filled
        )
        # Actually send the order to Alpaca; returns the order confirmation object.
        return self.client.submit_order(order)

    def close_position(self, symbol: str):
        # Sell the entire open position in this symbol at market price -
        # uses the slash-stripped form, same reasoning as the position
        # lookups above.
        return self.client.close_position(self._position_symbol(symbol))
