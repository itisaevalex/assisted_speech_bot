# Kernel Development Guide

## Overview

Kernels are pluggable trading strategies that run inside the `TradingEngine`. Each kernel is an async agent with access to market data, order execution, portfolio, and events.

## Kernel ABC

```python
class Kernel(ABC):
    name: str = "unnamed"
    required_exchange: str = ""  # Engine validates this before start

    async def start(self) -> None: ...     # Start strategy logic
    async def stop(self) -> None: ...      # Graceful shutdown
    def get_status(self) -> dict: ...      # Status for dashboard
```

## Lifecycle

1. **Register**: `engine.register_kernel(kernel)` — adds to engine's kernel dict
2. **Initialize**: `kernel.initialize(engine)` — stores engine reference, sets status to "starting"
3. **Start**: `kernel.start()` — runs strategy logic (usually starts a background task)
4. **Running**: kernel operates autonomously, submitting orders through `self.engine.execution`
5. **Stop**: `kernel.stop()` — cancels tasks, cleans up
6. **Stopped**: kernel is idle, can be restarted

## Engine Access

Inside `start()` and any async methods, access the engine via `self.engine`:

| Property | Type | Use |
|----------|------|-----|
| `self.engine.market_data` | `MarketDataClient` | Get prices, order books, midpoints |
| `self.engine.orders` | `OrderManager` | Create and track orders |
| `self.engine.execution` | `ExecutionEngine` | Submit orders (async) |
| `self.engine.portfolio` | `Portfolio` | Read positions and P&L |
| `self.engine.events` | `EventBus` | Publish/subscribe events |
| `self.engine.metrics` | `MetricsCollector` | Performance tracking |
| `self.engine.exchanges` | `dict[str, Exchange]` | Direct exchange access |

## Example: Simple Polling Kernel

```python
import asyncio
from polystation.core.kernel import Kernel
from polystation.kernels import register

@register
class MomentumKernel(Kernel):
    name = "momentum"

    def __init__(self, token_id: str, poll_interval: float = 30.0):
        super().__init__()
        self.token_id = token_id
        self.poll_interval = poll_interval
        self._task = None
        self._prev_price = None

    async def start(self):
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        if self._task:
            self._task.cancel()

    async def _loop(self):
        while True:
            mid = self.engine.market_data.get_midpoint(self.token_id)
            if mid and self._prev_price:
                change = (mid - self._prev_price) / self._prev_price
                if change > 0.02:  # 2% up
                    order = self.engine.orders.create_order(
                        self.token_id, "BUY", mid, 50, kernel_name=self.name
                    )
                    await self.engine.execution.submit_order(order)
            self._prev_price = mid
            await asyncio.sleep(self.poll_interval)
```

## Built-in Kernels

### Voice (`polystation/kernels/voice/`)
- Monitors audio streams (YouTube, Twitter, radio) for keywords
- Runs StreamTrader in a daemon thread (blocking I/O)
- Requires Vosk model + FFmpeg

### Market Maker (`polystation/kernels/market_maker/`)
- Places symmetric bid/ask around midpoint
- Cancels stale orders each cycle
- Respects max position limits

### Signal (`polystation/kernels/signal/`)
- Rolling price window with configurable lookback
- Momentum: buy when rising, sell when falling
- Mean reversion: buy when dipping, sell when spiking
- Configurable threshold and poll interval

### Agentic (`polystation/kernels/agentic/`)
- LLM-powered (Anthropic Claude or OpenAI)
- Data sources: market data, news feeds, YouTube transcripts, custom APIs
- Decision loop: gather context → LLM structured analysis → execute
- Configurable system prompt (trading thesis/narrative)
- Requires `pip install anthropic` or `pip install openai`

## Kernel Registration

The `@register` decorator auto-registers kernels by their `name` attribute:

```python
from polystation.kernels import list_kernels, create_kernel

print(list_kernels())  # ["voice", "market-maker", "signal", "agentic"]
kernel = create_kernel("signal", token_id="...", strategy="momentum")
```

## Testing Kernels

Use the `BacktestEngine` to test against historical data:

```python
from polystation.backtest.engine import BacktestEngine

engine = BacktestEngine(start_balance=10000.0)
result = await engine.run(kernel, price_data, token_id)
print(result.summary())
```

Or use dry-run mode in the dashboard — orders are logged but not sent to any exchange.
