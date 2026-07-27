"""
An in-memory stand-in for src.broker.Broker, used only in tests so
live_trade.py's decision logic can be exercised end-to-end without ever
touching the real Alpaca API. Mirrors Broker's public method signatures
exactly; anything calling one against the other shouldn't be able to
tell the difference except that this one never hits the network.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from uuid import uuid4

from alpaca.common.exceptions import APIError
from alpaca.trading.enums import OrderStatus


@dataclass
class FakeOrder:
    id: str
    symbol: str
    notional: float | None
    filled_qty: float
    filled_avg_price: float | None
    status: OrderStatus


class FakeBroker:
    def __init__(self, cash: float = 100_000.0, simulate_fills: bool = True):
        self.cash = cash
        self.is_paper = True
        # symbol -> (qty, avg_entry_price)
        self._positions: dict[str, tuple[float, float]] = {}
        # symbol -> FakeOrder, only while still "open" (unfilled)
        self._open_orders: dict[str, FakeOrder] = {}
        self._orders_by_id: dict[str, FakeOrder] = {}
        # Whether buy_notional/close_position simulate an instant fill
        # (the common case) or leave the order sitting open, to test the
        # "fill not confirmed" code path deliberately.
        self.simulate_fills = simulate_fills
        # Injected failures for testing error handling: symbol -> APIError
        # to raise the next time that symbol is looked up.
        self.inject_error: dict[str, APIError] = {}

    def get_cash(self) -> float:
        return self.cash

    def get_equity(self) -> float:
        equity = self.cash
        for symbol, (qty, avg_entry_price) in self._positions.items():
            equity += qty * avg_entry_price
        return equity

    def get_position_qty(self, symbol: str) -> float:
        if symbol in self.inject_error:
            raise self.inject_error.pop(symbol)
        qty, _ = self._positions.get(symbol, (0.0, 0.0))
        return qty

    def get_position_avg_entry_price(self, symbol: str) -> float | None:
        if symbol in self.inject_error:
            raise self.inject_error.pop(symbol)
        pos = self._positions.get(symbol)
        return pos[1] if pos else None

    def has_open_order(self, symbol: str) -> bool:
        return symbol in self._open_orders

    def get_order(self, order_id: str):
        return self._orders_by_id[order_id]

    def buy_notional(self, symbol: str, notional: float, is_crypto: bool = False):
        price = 100.0  # fixed fake fill price for simplicity
        qty = notional / price
        order = FakeOrder(
            id=str(uuid4()), symbol=symbol, notional=notional,
            filled_qty=qty if self.simulate_fills else 0.0,
            filled_avg_price=price if self.simulate_fills else None,
            status=OrderStatus.FILLED if self.simulate_fills else OrderStatus.ACCEPTED,
        )
        self._orders_by_id[order.id] = order
        if self.simulate_fills:
            existing_qty, existing_avg = self._positions.get(symbol, (0.0, 0.0))
            new_qty = existing_qty + qty
            new_avg = ((existing_qty * existing_avg) + (qty * price)) / new_qty if new_qty else price
            self._positions[symbol] = (new_qty, new_avg)
            self.cash -= notional
        else:
            self._open_orders[symbol] = order
        return order

    def close_position(self, symbol: str):
        qty, avg_entry_price = self._positions.get(symbol, (0.0, 0.0))
        order = FakeOrder(
            id=str(uuid4()), symbol=symbol, notional=None,
            filled_qty=qty if self.simulate_fills else 0.0,
            filled_avg_price=avg_entry_price if self.simulate_fills else None,
            status=OrderStatus.FILLED if self.simulate_fills else OrderStatus.ACCEPTED,
        )
        self._orders_by_id[order.id] = order
        if self.simulate_fills:
            self.cash += qty * avg_entry_price
            self._positions.pop(symbol, None)
        else:
            self._open_orders[symbol] = order
        return order


def make_not_found_error() -> APIError:
    """Builds an APIError shaped like Alpaca's real 404 'position not found'."""
    err = APIError('{"code": 40410000, "message": "position does not exist"}')
    err._http_error = SimpleNamespace(response=SimpleNamespace(status_code=404))
    return err


def make_server_error() -> APIError:
    """Builds an APIError shaped like a real 500 server failure - should
    NEVER be silently treated as 'no position' the way a 404 is."""
    err = APIError('{"code": 50000000, "message": "internal server error"}')
    err._http_error = SimpleNamespace(response=SimpleNamespace(status_code=500))
    return err
