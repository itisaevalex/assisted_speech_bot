"""Exchange abstraction layer — register and discover exchange adapters."""
from __future__ import annotations

from polystation.exchanges.base import Exchange

_REGISTRY: dict[str, Exchange] = {}


def register_exchange(exchange: Exchange) -> None:
    """Register an exchange adapter instance under its ``name``.

    Args:
        exchange: A connected or pre-configured :class:`Exchange` instance.
            The key used for registration is ``exchange.name``.
    """
    _REGISTRY[exchange.name] = exchange


def get_exchange(name: str) -> Exchange | None:
    """Look up a registered exchange adapter by name.

    Args:
        name: Short exchange identifier (e.g. ``"polymarket"``).

    Returns:
        The registered :class:`Exchange`, or None when not found.
    """
    return _REGISTRY.get(name)


def list_exchanges() -> list[str]:
    """Return the names of all registered exchange adapters.

    Returns:
        Sorted list of exchange name strings.
    """
    return list(_REGISTRY.keys())
