```
██████╗  ██████╗ ██╗  ██╗   ██╗███████╗████████╗ █████╗ ████████╗██╗ ██████╗ ███╗   ██╗
██╔══██╗██╔═══██╗██║  ╚██╗ ██╔╝██╔════╝╚══██╔══╝██╔══██╗╚══██╔══╝██║██╔═══██╗████╗  ██║
██████╔╝██║   ██║██║   ╚████╔╝ ███████╗   ██║   ███████║   ██║   ██║██║   ██║██╔██╗ ██║
██╔═══╝ ██║   ██║██║    ╚██╔╝  ╚════██║   ██║   ██╔══██║   ██║   ██║██║   ██║██║╚██╗██║
██║     ╚██████╔╝███████╗██║   ███████║   ██║   ██║  ██║   ██║   ██║╚██████╔╝██║ ╚████║
╚═╝      ╚═════╝ ╚══════╝╚═╝   ╚══════╝   ╚═╝   ╚═╝  ╚═╝   ╚═╝   ╚═╝ ╚═════╝ ╚═╝  ╚═══╝
```

**Universal trading kernel harness.** Multi-exchange support (Polymarket, Deribit, Binance), pluggable strategy kernels including LLM-powered agentic trading, live web dashboard with 6 tabs, backtesting, risk management, and full observability via Prometheus + Grafana.

![Polystation Dashboard](data/dashboard.png)

---

## Features

| Category | What's Built |
|----------|-------------|
| **Exchanges** | Polymarket CLOB, Deribit (WebSocket), Binance (REST), Paper (backtesting) |
| **Kernels** | Voice recognition, market maker, signal (momentum/mean-reversion), agentic (LLM) |
| **Dashboard** | 6 tabs — Trading, Logs, Settings, Performance, Risk, Backtest |
| **Risk** | RiskGuard (6 veto rules), position exit automation (trailing stop, profit target, stop loss) |
| **Persistence** | SQLite (orders, positions, trades, P&L snapshots) — survives restarts |
| **Monitoring** | Prometheus /metrics, Grafana dashboards, Redis (optional) |
| **Backtesting** | PaperExchange + BacktestEngine with Sharpe ratio, drawdown, P&L curves |
| **Tests** | 757 tests (live API, no mocking, E2E flows) |

## Architecture

```
polystation/
├── core/                        # Engine & framework
│   ├── engine.py                # TradingEngine — kernel lifecycle, exchange registry
│   ├── kernel.py                # Kernel ABC — base for all strategies
│   ├── portfolio.py             # Position tracking, VWAP, P&L
│   ├── orders.py                # Order lifecycle (7 states), fill tracking
│   ├── events.py                # Async event bus
│   ├── metrics.py               # MetricsCollector — in-memory performance tracking
│   ├── risk.py                  # RiskGuard — pre-trade veto system
│   └── prometheus.py            # Prometheus gauge/counter management
│
├── exchanges/                   # Exchange abstraction layer
│   ├── base.py                  # Exchange ABC (async), OrderType, OrderResult
│   ├── polymarket.py            # Polymarket CLOB adapter
│   ├── deribit.py               # Deribit WebSocket adapter (perps + futures)
│   ├── binance.py               # Binance REST adapter (spot + USDM futures)
│   └── paper.py                 # PaperExchange for backtesting
│
├── kernels/                     # Pluggable trading strategies
│   ├── voice/                   # Speech recognition → trade on keywords
│   ├── market_maker/            # Spread-based market making
│   ├── signal/                  # Momentum / mean-reversion signals
│   └── agentic/                 # LLM-powered (Claude/OpenAI) with data sources
│
├── automation/                  # Position exit automation
│   └── position_manager.py      # Trailing stop, profit target, time exit
│
├── persistence/                 # SQLite state management
│   ├── database.py              # StateDatabase — CRUD, restore on startup
│   └── models.py                # Table schemas (5 tables, WAL mode)
│
├── backtest/                    # Backtesting framework
│   └── engine.py                # BacktestEngine + BacktestResult
│
├── market/                      # Market data layer
│   ├── client.py                # CLOB REST wrapper
│   ├── book.py                  # OrderBook model
│   ├── scanner.py               # Gamma API discovery + /public-search
│   └── feed.py                  # WebSocket feed with auto-reconnect
│
├── dashboard/                   # Web dashboard (FastAPI)
│   ├── app.py                   # Application factory, lifespan wiring
│   ├── ws.py                    # WebSocket hub with market subscriptions
│   ├── api/                     # 35+ REST endpoints
│   │   ├── markets.py           # Market data, search, price history
│   │   ├── orders.py            # Order CRUD, manual placement
│   │   ├── strategies.py        # Kernel deploy/stop
│   │   ├── portfolio.py         # Positions, P&L
│   │   ├── performance.py       # Performance metrics, trade history
│   │   ├── risk.py              # RiskGuard, exit config
│   │   ├── backtest.py          # Run backtests, load history
│   │   ├── config.py            # Credentials, dry-run toggle
│   │   └── metrics_endpoint.py  # Prometheus /metrics
│   └── static/                  # Dark terminal UI (6 tabs)
│
├── infra/                       # Infrastructure
│   └── redis_client.py          # Optional Redis (graceful degradation)
│
├── trading/                     # Execution layer
│   ├── execution.py             # Async ExecutionEngine
│   ├── client.py                # Legacy CLOB client
│   ├── orders.py                # Order submission with backoff
│   └── recorder.py              # JSON file persistence
│
├── wallet/                      # Blockchain wallet management
├── speech/                      # Vosk speech recognition
└── sources/                     # Audio stream sources (YouTube, Twitter, radio)

monitoring/                      # Prometheus + Grafana configs
├── prometheus.yml
└── grafana/
    ├── provisioning/            # Auto-provisioned datasource + dashboards
    └── dashboards/
        └── polystation.json     # 10-panel Grafana dashboard

deploy/                          # Deployment tooling
├── deploy.sh                    # Git pull + docker build + health check
└── polystation.service          # systemd unit file
```

## Quick Start

```bash
# Install
git clone https://github.com/itisaevalex/polystation.git
cd polystation
pip install -e ".[dev]"

# Launch dashboard (dry-run mode — no real trades)
uvicorn polystation.dashboard.app:create_app --factory --port 8420

# Open http://localhost:8420
```

## Docker Deployment

```bash
# Full stack: Polystation + Redis + Prometheus + Grafana
cp .env.example .env  # Edit with your API keys
docker compose up -d

# Dashboard:   http://localhost:8420
# Grafana:     http://localhost:3000 (admin/polystation)
# Prometheus:  http://localhost:9090
```

## Dashboard Tabs

| Tab | What It Shows |
|-----|---------------|
| **Trading** | Markets (with favorites), order book, strategies, orders, portfolio, trade log, quick trade |
| **Logs** | Full-screen log viewer with level filters (INFO/TRADE/WARN/ERROR), export |
| **Settings** | API credentials, dry-run toggle, dashboard config |
| **Performance** | P&L chart (realized/unrealized/total), per-kernel stats, trade history, win rates |
| **Risk** | RiskGuard config, exit automation config, exposure, positions, daily P&L |
| **Backtest** | Run strategies against historical data, P&L curve, Sharpe ratio, drawdown |

## Exchange Adapters

All exchanges implement the async `Exchange` ABC. Kernels are exchange-agnostic.

| Exchange | Type | Auth | Status |
|----------|------|------|--------|
| Polymarket | CLOB REST | API key + PK | Production |
| Deribit | WebSocket (JSON-RPC) | API key + secret | Ready (testnet default) |
| Binance | REST + HMAC | API key + secret | Ready (spot + futures) |
| Paper | In-memory simulation | None | For backtesting |

```python
# Kernels talk to any exchange through the same interface
result = await exchange.place_order("BTCUSDT", "BUY", 65000.0, 0.01)
book = await exchange.get_orderbook("BTC-PERPETUAL")
mid = await exchange.get_midpoint(token_id)
```

## Trading Kernels

### Voice Kernel
Monitors YouTube/Twitter/radio audio for keywords, triggers trades on detection.

### Market Maker Kernel
Places symmetric bid/ask around the midpoint. Configurable spread, size, refresh interval, position limits.

### Signal Kernel
Momentum or mean-reversion signals from rolling price window. Configurable lookback, threshold, poll interval.

### Agentic Kernel
LLM-powered trading decisions. Gathers context from data sources (market data, news, YouTube transcripts), sends to Claude/OpenAI for structured analysis, executes the decision.

```python
kernel = AgenticKernel(
    system_prompt="You are a crypto trader focused on BTC prediction markets...",
    model="claude-sonnet-4-20250514",
    symbols=["<token_id>"],
    decision_interval=300,  # 5 minutes
    news_enabled=True,
)
```

### Custom Kernels

```python
from polystation.core.kernel import Kernel
from polystation.kernels import register

@register
class MyKernel(Kernel):
    name = "my-strategy"
    required_exchange = "polymarket"  # optional — engine validates before start

    async def start(self) -> None:
        # self.engine.exchanges["polymarket"]  — exchange adapter
        # self.engine.market_data              — prices, order books
        # self.engine.orders                   — create/track orders
        # self.engine.execution                — submit orders (async)
        # self.engine.portfolio                — positions and P&L
        # self.engine.events                   — pub/sub event bus
        # self.engine.metrics                  — performance tracking
        ...

    async def stop(self) -> None:
        ...
```

## Risk Management

### RiskGuard (pre-trade)
6 configurable veto rules checked before every order submission:

| Rule | Default | Description |
|------|---------|-------------|
| Max stake per trade | $500 | Rejects orders above this value |
| Max gross exposure | $10,000 | Rejects if total exposure would exceed |
| Max position per token | $1,000 | Caps per-token concentration |
| Daily loss stop | -$500 | Halts all trading after daily loss |
| Max active orders | 50 | Prevents order flooding |
| Max daily trades | 200 | Rate limits trading activity |

### Position Exit Automation
Background monitor with configurable rules per-position or globally:
- **Trailing stop**: Exit if price drops X% from peak
- **Profit target**: Exit at +X% unrealized P&L
- **Stop loss**: Exit at -X% unrealized P&L
- **Max hold time**: Exit after N hours
- **Expiry exit**: Exit N hours before market expiry

## Backtesting

```python
from polystation.backtest.engine import BacktestEngine
from polystation.kernels.signal.kernel import SignalKernel

kernel = SignalKernel(token_id="...", strategy="momentum", threshold=0.02)
engine = BacktestEngine(start_balance=10000.0, slippage_bps=5.0)
result = await engine.run(kernel, price_data, token_id)

print(result.summary())
# P&L: $+142.50 | Trades: 23 | Win Rate: 65.2% | Max DD: $45.20 | Sharpe: 1.84
```

Or use the dashboard Backtest tab — load real price history from any Polymarket market and run strategies visually.

## Observability

### Built-in (zero dependencies)
- Performance tab: P&L charts, per-kernel stats, trade history
- Risk tab: exposure gauges, position limits, RiskGuard status

### Prometheus + Grafana (optional)
```bash
docker compose -f docker-compose.monitoring.yml up -d
# Grafana: http://localhost:3000
```

15 Prometheus gauges/counters: P&L by kernel, positions, exposure, trade count, win rate, engine/kernel status, WebSocket connections, queue depth.

10-panel Grafana dashboard auto-provisioned on startup.

### Redis (optional)
```bash
export REDIS_URL=redis://localhost:6379/0
```
Adds trade publishing, portfolio snapshots, heartbeats, dead-letter queue. All methods are no-ops when Redis is unavailable.

## API Reference

Full API docs at `http://localhost:8420/docs` (auto-generated Swagger UI).

| Category | Endpoints |
|----------|-----------|
| Markets | `GET /api/markets/`, `/trending`, `/search`, `/book/{id}`, `/price/{id}`, `/history/{id}`, `/health` |
| Orders | `GET /api/orders/`, `/active`, `/summary`, `/{id}` ; `POST /api/orders/create` |
| Strategies | `GET /api/strategies/`, `/available`, `/{name}` ; `POST /start`, `/stop/{name}` |
| Portfolio | `GET /api/portfolio/`, `/positions`, `/pnl` |
| Performance | `GET /api/performance/summary`, `/pnl-history`, `/trades`, `/kernels` |
| Risk | `GET /api/risk/summary`, `/positions`, `/guard`, `/exits` ; `POST /guard`, `/exits` |
| Backtest | `POST /api/backtest/run` ; `GET /api/backtest/history/{id}` |
| Config | `GET/POST /api/config/dry-run`, `POST /api/config/credentials` |
| Monitoring | `GET /metrics` (Prometheus format) |
| WebSocket | `WS /ws` (subscribe to market updates) |

## Configuration

### Environment Variables

Copy `.env.example` to `.env`:

| Variable | Description |
|----------|-------------|
| `HOST` | Polymarket API host |
| `PK` | Wallet private key |
| `PBK` | Wallet public key |
| `CLOB_API_KEY` | CLOB API key |
| `CLOB_SECRET` | CLOB API secret |
| `CLOB_PASS_PHRASE` | CLOB API passphrase |
| `REDIS_URL` | Redis connection URL (optional) |

### YAML Config

| File | Purpose |
|------|---------|
| `config/settings.yaml` | Trading limits, speech settings, paths, risk parameters |
| `config/markets.yaml` | Market definitions with keywords |
| `config/sources/*.yaml` | Audio source configs (YouTube, Twitter, radio) |
| `config/exchanges/deribit.yaml` | Deribit API credentials and instruments |
| `config/exchanges/binance.yaml` | Binance API credentials and symbols |

## Development

```bash
pip install -e ".[dev]"

# Run all 757 tests (live API, no mocking)
pytest

# Run E2E tests only
pytest tests/test_e2e.py -v

# Lint
ruff check polystation/

# Type check
mypy polystation/
```

### Optional dependencies

```bash
pip install -e ".[monitoring]"   # prometheus_client, redis
pip install -e ".[agentic]"      # anthropic (for agentic kernel)
pip install -e ".[notebook]"     # jupyter, numpy, pandas
```

## Documentation

| Document | Description |
|----------|-------------|
| [README.md](README.md) | This file — overview, quick start, architecture |
| [CLAUDE.md](CLAUDE.md) | Development context, build checklist, commands |
| [docs/exchanges.md](docs/exchanges.md) | Exchange adapter guide |
| [docs/kernels.md](docs/kernels.md) | Kernel development guide |
| [docs/deployment.md](docs/deployment.md) | Deployment and operations |
| [docs/api.md](docs/api.md) | API reference (or use /docs endpoint) |

## Links

- [Polymarket CLOB API](https://docs.polymarket.com/)
- [Deribit API](https://docs.deribit.com/)
- [Binance API](https://binance-docs.github.io/apidocs/)
- [Gamma API /public-search](https://gamma-api.polymarket.com/public-search?q=bitcoin)

## Disclaimer

Experimental / educational. Use at your own risk. This software interacts with live financial markets. Always start in dry-run mode and verify behavior before enabling live execution.

## License

MIT
