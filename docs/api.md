# API Reference

Auto-generated Swagger docs available at `http://localhost:8420/docs`.

## Markets

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/markets/` | Paginated active markets (offset, limit, order) |
| GET | `/api/markets/trending` | Highest 24h volume markets |
| GET | `/api/markets/search?q=bitcoin` | Full-text search via Gamma /public-search |
| GET | `/api/markets/book/{token_id}` | Order book snapshot (bids, asks, spread) |
| GET | `/api/markets/price/{token_id}` | Midpoint, best bid/ask, spread |
| GET | `/api/markets/history/{token_id}` | Price history (1d/1w/1m/max intervals) |
| GET | `/api/markets/health` | CLOB connectivity + server time |

## Orders

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/orders/` | Recent orders (limit param) |
| GET | `/api/orders/active` | Active orders (optional kernel filter) |
| GET | `/api/orders/summary` | Order counts and recent list |
| GET | `/api/orders/{order_id}` | Single order detail |
| POST | `/api/orders/create` | Manual order placement |

### POST /api/orders/create
```json
{
    "token_id": "8285508889...",
    "side": "BUY",
    "price": 0.50,
    "size": 50.0,
    "order_type": "GTC"
}
```

## Strategies

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/strategies/` | Engine status + all kernel statuses |
| GET | `/api/strategies/available` | Registered kernel names |
| GET | `/api/strategies/{name}` | Single kernel detail |
| POST | `/api/strategies/start` | Deploy a kernel |
| POST | `/api/strategies/stop/{name}` | Stop a kernel |

### POST /api/strategies/start
```json
{
    "name": "signal",
    "params": {
        "token_id": "8285508889...",
        "strategy": "momentum",
        "threshold": 0.02
    }
}
```

## Portfolio

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/portfolio/` | Full summary (positions, P&L, trade count) |
| GET | `/api/portfolio/positions` | Open positions only |
| GET | `/api/portfolio/pnl` | Realized, unrealized, total P&L |

## Performance

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/performance/summary` | Aggregate stats (trades, P&L, win rate) |
| GET | `/api/performance/pnl-history` | P&L time-series (5s snapshots, 12h retention) |
| GET | `/api/performance/trades` | Recent trade history with kernel labels |
| GET | `/api/performance/kernels` | Per-kernel performance breakdown |

## Risk

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/risk/summary` | Exposure, positions, daily P&L |
| GET | `/api/risk/positions` | Per-position risk (weight, P&L) |
| GET | `/api/risk/guard` | RiskGuard config + status + vetoes |
| POST | `/api/risk/guard` | Update RiskGuard limits |
| GET | `/api/risk/exits` | Exit automation config + history |
| POST | `/api/risk/exits` | Update exit automation rules |

### POST /api/risk/exits
```json
{
    "enabled": true,
    "trailing_stop_pct": 5.0,
    "profit_target_pct": 20.0,
    "stop_loss_pct": 10.0,
    "max_hold_hours": 24.0
}
```

## Backtest

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/backtest/run` | Run a backtest with price data |
| GET | `/api/backtest/history/{token_id}` | Fetch historical prices for backtesting |

### POST /api/backtest/run
```json
{
    "kernel_type": "signal",
    "strategy": "momentum",
    "token_id": "8285508889...",
    "prices": [0.45, 0.47, 0.50, 0.48, 0.52, 0.55],
    "start_balance": 10000.0,
    "threshold": 0.02
}
```

## Config

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/config/dry-run` | Current dry-run state |
| POST | `/api/config/dry-run?enabled=true` | Toggle dry-run mode |
| POST | `/api/config/credentials` | Set API keys + initialize live trading |

## Monitoring

| Method | Path | Description |
|--------|------|-------------|
| GET | `/metrics` | Prometheus text format (15 gauges/counters) |

## WebSocket

Connect to `ws://localhost:8420/ws` for real-time updates.

### Client → Server messages
```json
{"type": "subscribe_market", "token_id": "..."}
{"type": "unsubscribe_market", "token_id": "..."}
```

### Server → Client messages
```json
{"type": "book_update", "token_id": "...", "data": {...}}
{"type": "subscribed_market", "token_id": "..."}
```
