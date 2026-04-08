# Deployment Guide

## Quick Start (Local)

```bash
pip install -e .
uvicorn polystation.dashboard.app:create_app --factory --port 8420
```

## Docker (Recommended)

```bash
cp .env.example .env  # Edit with your API keys
docker compose up -d
```

Services:
| Service | Port | Description |
|---------|------|-------------|
| polystation | 8420 | Trading station + dashboard |
| redis | 6379 | State cache, trade queue |
| prometheus | 9090 | Metrics scraping |
| grafana | 3000 | Dashboards (admin/polystation) |

## Home Server Deployment

### Prerequisites
- Ubuntu/Pop!OS (or any Linux with Docker)
- 16GB+ RAM recommended
- Docker + Docker Compose installed
- Git

### Setup

```bash
# Clone
git clone git@github.com:youruser/polystation-private.git /opt/polystation
cd /opt/polystation

# Configure
cp .env.example .env
nano .env  # Add your API keys

# Deploy
./deploy/deploy.sh
```

### Auto-start on Boot

```bash
sudo cp deploy/polystation.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable polystation
sudo systemctl start polystation
```

### Remote Access

Use Tailscale or WireGuard to access the dashboard securely:

```bash
# Install Tailscale on both machines
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up

# Access dashboard via Tailscale IP
# http://100.x.y.z:8420
```

## Deploy Script

`deploy/deploy.sh` does:
1. `git pull --ff-only` (fetch latest code)
2. `docker compose build` (rebuild containers)
3. `docker compose up -d` (restart services)
4. Health check (30s timeout)
5. Print service URLs

Use `./deploy/deploy.sh --rebuild` to force a fresh build.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `HOST` | For live trading | Polymarket API host |
| `PK` | For live trading | Wallet private key |
| `PBK` | For live trading | Wallet public key |
| `CLOB_API_KEY` | For live trading | CLOB API key |
| `CLOB_SECRET` | For live trading | CLOB API secret |
| `CLOB_PASS_PHRASE` | For live trading | CLOB API passphrase |
| `REDIS_URL` | No | Redis URL (default: tries localhost) |

## Health Checks

```bash
# API health
curl http://localhost:8420/api/markets/health

# Docker health
docker compose ps

# Logs
docker compose logs -f polystation
```

## Monitoring

### Built-in Dashboard
- http://localhost:8420 → Performance tab (P&L charts, trade history)
- http://localhost:8420 → Risk tab (exposure, RiskGuard status)

### Grafana
- http://localhost:3000 (auto-provisioned dashboard)
- 10 panels: P&L, positions, trades, win rate, exposure, engine status

### Prometheus
- http://localhost:9090
- Scrapes http://polystation:8420/metrics every 5 seconds

## Backup

SQLite database at `data/polystation.db` contains all orders, positions, trades, and P&L snapshots. Back it up periodically:

```bash
cp data/polystation.db data/polystation.db.bak.$(date +%Y%m%d)
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Dashboard won't start | Check `docker compose logs polystation` |
| No market data | Verify internet connectivity, check CLOB health |
| Orders rejected | Check RiskGuard config, verify credentials |
| Redis not connecting | Check `REDIS_URL`, verify Redis is running |
| Grafana empty | Wait 30s for first scrape, check Prometheus targets |
