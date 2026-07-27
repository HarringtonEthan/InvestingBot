"""
An in-memory stand-in for src.broker.Broker, used only in tests so
live_trade.py's decision logic can be exercised end-to-end without ever
touching the real Alpaca API. Mirrors Broker's public method signatures
exactly; anything calling one against the other shouldn't be able to
tell the difference except that this one never hits the network.
"""

# Lets type hints work without issue in this Python version.
from __future__ import annotations

# dataclass is a shortcut for a small class that just holds a few named
# fields (FakeOrder below) without hand-writing __init__.
from dataclasses import dataclass
# A quick way to build a throwaway object with arbitrary attributes -
# used below to fake Alpaca's nested error-response shape.
from types import SimpleNamespace
# Generates unique fake order IDs, the same way Alpaca's real order IDs
# are UUIDs.
from uuid import uuid4

# The real exception type Broker catches - reused here so tests can
# inject realistic-looking failures.
from alpaca.common.exceptions import APIError
# The real status enum Broker/live_trade.py check against.
from alpaca.trading.enums import OrderStatus


@dataclass
class FakeOrder:
    id: str                        # unique fake order ID
    symbol: str                    # which asset this order is for
    notional: float | None         # dollar amount, for BUY orders (None for SELL/close)
    filled_qty: float              # how much actually filled (0.0 if still unfilled)
    filled_avg_price: float | None  # the fill price, or None if unfilled
    status: OrderStatus            # FILLED or ACCEPTED (unfilled), mirroring Alpaca's real statuses


class FakeBroker:
    def __init__(self, cash: float = 100_000.0, simulate_fills: bool = True):
        # Starting cash balance for this fake account.
        self.cash = cash
        # Broker.is_paper is read by some callers - always True here,
        # since this is never anything but a test double.
        self.is_paper = True
        # symbol -> (qty, avg_entry_price) for every currently open position.
        self._positions: dict[str, tuple[float, float]] = {}
        # symbol -> FakeOrder, only while that order is still "open"
        # (i.e. simulate_fills was False when it was placed).
        self._open_orders: dict[str, FakeOrder] = {}
        # order_id -> FakeOrder, every order ever placed, filled or not -
        # this is what get_order() looks up by ID.
        self._orders_by_id: dict[str, FakeOrder] = {}
        # Whether buy_notional/close_position simulate an instant fill
        # (the common case) or leave the order sitting open, to test the
        # "fill not confirmed" code path deliberately.
        self.simulate_fills = simulate_fills
        # Injected failures for testing error handling: symbol -> APIError
        # to raise the next time that symbol is looked up. Popped (used
        # once) rather than persisted, so a test can inject exactly one
        # failure and let subsequent calls succeed normally.
        self.inject_error: dict[str, APIError] = {}

    def get_cash(self) -> float:
        # Mirrors Broker.get_cash() - just returns the current balance.
        return self.cash

    def get_equity(self) -> float:
        # Mirrors Broker.get_equity(): cash plus the current value of
        # every open position (qty * the price it was "entered" at,
        # since this fake has no separate live market price feed).
        equity = self.cash
        for symbol, (qty, avg_entry_price) in self._positions.items():
            equity += qty * avg_entry_price
        return equity

    def get_position_qty(self, symbol: str) -> float:
        # If this symbol has an injected failure queued, raise it now
        # (and remove it, so it only fires once) instead of returning a
        # real answer - lets tests simulate a broker error mid-run.
        if symbol in self.inject_error:
            raise self.inject_error.pop(symbol)
        # No position on record for this symbol defaults to (0.0, 0.0) -
        # matches Broker's real "genuinely no position" behavior.
        qty, _ = self._positions.get(symbol, (0.0, 0.0))
        return qty

    def get_position_avg_entry_price(self, symbol: str) -> float | None:
        if symbol in self.inject_error:
            raise self.inject_error.pop(symbol)
        pos = self._positions.get(symbol)
        # pos[1] is the avg_entry_price half of the (qty, avg_entry_price)
        # tuple; None if no position is on record at all.
        return pos[1] if pos else None

    def has_open_order(self, symbol: str) -> bool:
        # True only if buy_notional/close_position was called with
        # simulate_fills=False for this symbol and hasn't been "filled"
        # by a test since.
        return symbol in self._open_orders

    def get_order(self, order_id: str):
        # Mirrors Broker.get_order() - look up by the ID returned when
        # the order was originally placed.
        return self._orders_by_id[order_id]

    def buy_notional(self, symbol: str, notional: float, is_crypto: bool = False):
        price = 100.0  # fixed fake fill price for simplicity
        qty = notional / price  # how many units that dollar amount buys at the fake price
        order = FakeOrder(
            id=str(uuid4()), symbol=symbol, notional=notional,
            # If simulating an instant fill, report the full quantity/price
            # filled immediately; otherwise report an unfilled order
            # (0 qty, no price, status ACCEPTED) so poll_for_fill() in
            # live_trade.py has something real to poll against.
            filled_qty=qty if self.simulate_fills else 0.0,
            filled_avg_price=price if self.simulate_fills else None,
            status=OrderStatus.FILLED if self.simulate_fills else OrderStatus.ACCEPTED,
        )
        # Every order, filled or not, gets remembered by ID so get_order()
        # can find it later.
        self._orders_by_id[order.id] = order
        if self.simulate_fills:
            # Update the position: combine whatever was already held
            # with this new purchase, weighting the average entry price
            # by how many units came from each.
            existing_qty, existing_avg = self._positions.get(symbol, (0.0, 0.0))
            new_qty = existing_qty + qty
            new_avg = ((existing_qty * existing_avg) + (qty * price)) / new_qty if new_qty else price
            self._positions[symbol] = (new_qty, new_avg)
            # Buying spends cash.
            self.cash -= notional
        else:
            # Not simulating a fill - leave the order sitting open so
            # has_open_order() reports it and a test can later call
            # get_order() to see it still unfilled.
            self._open_orders[symbol] = order
        return order

    def close_position(self, symbol: str):
        # Whatever's currently held gets fully liquidated - look it up
        # first so the fill (if simulated) can report the real quantity.
        qty, avg_entry_price = self._positions.get(symbol, (0.0, 0.0))
        order = FakeOrder(
            id=str(uuid4()), symbol=symbol, notional=None,
            filled_qty=qty if self.simulate_fills else 0.0,
            filled_avg_price=avg_entry_price if self.simulate_fills else None,
            status=OrderStatus.FILLED if self.simulate_fills else OrderStatus.ACCEPTED,
        )
        self._orders_by_id[order.id] = order
        if self.simulate_fills:
            # Selling returns cash (at the same price it was "bought"
            # at, since this fake broker has no separate live price feed
            # to sell at a different price than entry).
            self.cash += qty * avg_entry_price
            # Position is now fully closed - remove it entirely rather
            # than leaving a zero-quantity entry behind.
            self._positions.pop(symbol, None)
        else:
            self._open_orders[symbol] = order
        return order


def make_not_found_error() -> APIError:
    """Builds an APIError shaped like Alpaca's real 404 'position not found'."""
    # APIError's constructor expects a JSON string body, matching what
    # Alpaca's real API actually returns on a 404.
    err = APIError('{"code": 40410000, "message": "position does not exist"}')
    # APIError.status_code reads this nested attribute path - fake just
    # enough of it to make that property return 404, without needing a
    # real HTTP response object.
    err._http_error = SimpleNamespace(response=SimpleNamespace(status_code=404))
    return err


def make_server_error() -> APIError:
    """Builds an APIError shaped like a real 500 server failure - should
    NEVER be silently treated as 'no position' the way a 404 is."""
    err = APIError('{"code": 50000000, "message": "internal server error"}')
    err._http_error = SimpleNamespace(response=SimpleNamespace(status_code=500))
    return err
