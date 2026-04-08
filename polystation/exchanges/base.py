"""Abstract exchange interface and shared data models."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


class OrderType(str, Enum):
    """Time-in-force order types supported across exchange adapters."""

    GTC = "GTC"
    FOK = "FOK"
    IOC = "IOC"
    GTD = "GTD"
    MARKET = "MARKET"


@dataclass
class OrderResult:
    """Result of a single order submission attempt.

    Attributes:
        order_id: Exchange-assigned order identifier.
        status: Outcome string — ``"accepted"``, ``"filled"``, or ``"rejected"``.
        filled_price: Actual fill price, if available.
        filled_size: Number of shares filled, if available.
        error: Human-readable error message when status is ``"rejected"``.
    """

    order_id: str
    status: str  # "accepted", "filled", "rejected"
    filled_price: float | None = None
    filled_size: float | None = None
    error: str | None = None


@dataclass
class ExchangeOrderBook:
    """Exchange-normalised order book snapshot.

    Attributes:
        symbol: Token or instrument identifier.
        bids: Price levels on the bid side as ``(price, size)`` tuples,
            sorted highest-price-first.
        asks: Price levels on the ask side as ``(price, size)`` tuples,
            sorted lowest-price-first.
        timestamp: ISO-8601 or exchange-native timestamp string.
    """

    symbol: str
    bids: list[tuple[float, float]] = field(default_factory=list)
    asks: list[tuple[float, float]] = field(default_factory=list)
    timestamp: str = ""

    @property
    def best_bid(self) -> float | None:
        """Highest bid price, or None when the bid side is empty."""
        return self.bids[0][0] if self.bids else None

    @property
    def best_ask(self) -> float | None:
        """Lowest ask price, or None when the ask side is empty."""
        return self.asks[0][0] if self.asks else None


@dataclass
class ExchangePosition:
    """Normalised position snapshot returned by an exchange adapter.

    Attributes:
        symbol: Token or instrument identifier.
        side: ``"BUY"`` (long) or ``"SELL"`` (short).
        size: Current position size.
        avg_entry_price: Volume-weighted average entry price.
        unrealized_pnl: Floating P&L at the current mark price.
    """

    symbol: str
    side: str
    size: float
    avg_entry_price: float
    unrealized_pnl: float = 0.0


Callback = Callable[..., Coroutine[Any, Any, None]]


class Exchange(ABC):
    """Abstract base class for exchange adapters.

    All methods are async.  Synchronous exchange clients must be
    wrapped with ``asyncio.to_thread()`` inside the implementation.

    Class attributes:
        name: Short identifier for this exchange (e.g. ``"polymarket"``).
            Must be overridden in every concrete subclass.
    """

    name: str = "unknown"

    @abstractmethod
    async def connect(self) -> None:
        """Initialize the connection to the exchange."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Clean up connections and release resources."""
        ...

    @abstractmethod
    async def place_order(
        self,
        symbol: str,
        side: str,
        price: float,
        size: float,
        order_type: OrderType = OrderType.GTC,
    ) -> OrderResult:
        """Submit a new order.

        Args:
            symbol: Token or instrument identifier.
            side: ``"BUY"`` or ``"SELL"``.
            price: Limit price.
            size: Order quantity.
            order_type: Time-in-force instruction.

        Returns:
            An :class:`OrderResult` describing the submission outcome.
        """
        ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a single open order by its exchange-assigned ID.

        Args:
            order_id: Exchange-assigned order identifier.

        Returns:
            True on successful cancellation, False otherwise.
        """
        ...

    @abstractmethod
    async def cancel_all_orders(self, symbol: str | None = None) -> int:
        """Cancel all open orders, optionally scoped to one symbol.

        Args:
            symbol: When provided, only orders for this symbol are cancelled.

        Returns:
            Number of orders successfully cancelled (best-effort estimate).
        """
        ...

    @abstractmethod
    async def get_orderbook(self, symbol: str) -> ExchangeOrderBook:
        """Fetch the current order book for a symbol.

        Args:
            symbol: Token or instrument identifier.

        Returns:
            An :class:`ExchangeOrderBook` snapshot.
        """
        ...

    @abstractmethod
    async def get_positions(self) -> list[ExchangePosition]:
        """Return all open positions held on this exchange.

        Returns:
            List of :class:`ExchangePosition` objects.
        """
        ...

    @abstractmethod
    async def get_balance(self) -> dict[str, float]:
        """Return available balances keyed by asset symbol.

        Returns:
            Mapping of asset symbol to available balance.
        """
        ...

    @abstractmethod
    async def get_midpoint(self, symbol: str) -> float | None:
        """Get the current mid-market price for a symbol.

        Args:
            symbol: Token or instrument identifier.

        Returns:
            Mid-market price, or None when unavailable.
        """
        ...

    @abstractmethod
    async def get_price(self, symbol: str, side: str) -> float | None:
        """Get the best price for a symbol on the given side.

        Args:
            symbol: Token or instrument identifier.
            side: ``"BUY"`` or ``"SELL"``.

        Returns:
            Best price for the side, or None when unavailable.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check whether the exchange API is reachable and operational.

        Returns:
            True when the exchange reports healthy, False otherwise.
        """
        ...
