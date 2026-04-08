# Exchange Adapter Guide

## Overview

Polystation uses an abstract `Exchange` interface so kernels work with any exchange. All methods are `async`.

## Exchange ABC

```python
class Exchange(ABC):
    name: str

    async def connect(self) -> None
    async def disconnect(self) -> None
    async def place_order(symbol, side, price, size, order_type) -> OrderResult
    async def cancel_order(order_id) -> bool
    async def cancel_all_orders(symbol=None) -> int
    async def get_orderbook(symbol) -> ExchangeOrderBook
    async def get_positions() -> list[ExchangePosition]
    async def get_balance() -> dict[str, float]
    async def get_midpoint(symbol) -> float | None
    async def get_price(symbol, side) -> float | None
    async def health_check() -> bool
```

## Shared Data Models

| Model | Fields |
|-------|--------|
| `OrderResult` | order_id, status ("accepted"/"filled"/"rejected"), filled_price, filled_size, error |
| `ExchangeOrderBook` | symbol, bids [(price, size)], asks [(price, size)], timestamp |
| `ExchangePosition` | symbol, side, size, avg_entry_price, unrealized_pnl |
| `OrderType` | GTC, FOK, IOC, GTD, MARKET |

## Polymarket Adapter

- File: `polystation/exchanges/polymarket.py`
- Uses `py-clob-client` (synchronous) wrapped in `asyncio.to_thread()`
- Read-only market data always works (no auth needed)
- Trading requires `PK` + `CLOB_API_KEY` env vars
- `get_positions()` and `get_balance()` return empty (no CLOB endpoint)

## Deribit Adapter

- File: `polystation/exchanges/deribit.py`
- WebSocket-first (JSON-RPC protocol)
- Auth via `public/auth` with API key + secret
- Supports BTC-PERPETUAL, ETH-PERPETUAL, futures
- Config: `config/exchanges/deribit.yaml`
- Default: testnet (`test.deribit.com`)

## Binance Adapter

- File: `polystation/exchanges/binance.py`
- REST via `aiohttp` (no `python-binance` dependency)
- HMAC-SHA256 signature for authenticated endpoints
- Supports spot and USDM futures
- Config: `config/exchanges/binance.yaml`
- Default: testnet

## Paper Exchange

- File: `polystation/exchanges/paper.py`
- In-memory simulation for backtesting
- Configurable slippage (`slippage_bps`)
- Tracks balance, positions, trade log
- `set_price(symbol, price)` to feed historical data
- `get_pnl()` for mark-to-market P&L
- `reset()` to clear state

## Writing a New Adapter

```python
from polystation.exchanges.base import Exchange, OrderResult, ExchangeOrderBook, OrderType

class MyExchange(Exchange):
    name = "my-exchange"

    async def connect(self) -> None:
        # Initialize client, authenticate
        ...

    async def place_order(self, symbol, side, price, size, order_type=OrderType.GTC):
        # Submit order to exchange
        return OrderResult(order_id="...", status="filled", filled_price=price, filled_size=size)

    # ... implement all abstract methods
```

Register in `polystation/dashboard/app.py` lifespan:
```python
my_exchange = MyExchange(api_key="...")
await my_exchange.connect()
engine.register_exchange(my_exchange)
```
