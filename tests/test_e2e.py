"""End-to-end integration tests — exercise full API flows.

NO MOCKING.  The app starts in dry-run mode so no real trades happen.
All tests require a live internet connection to hit the Polymarket API.
"""
from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

from polystation.dashboard.app import create_app


# ---------------------------------------------------------------------------
# Helper: resolve a live token_id
# ---------------------------------------------------------------------------

def _get_active_token_id() -> str:
    """Return an active token_id from the Gamma API, or skip the test."""
    import requests as _req

    resp = _req.get(
        "https://gamma-api.polymarket.com/markets",
        params={"limit": "20", "active": "true", "closed": "false"},
        timeout=15,
    )
    resp.raise_for_status()
    for m in resp.json():
        clob_ids = m.get("clobTokenIds")
        if not clob_ids:
            continue
        if isinstance(clob_ids, str):
            try:
                clob_ids = json.loads(clob_ids)
            except (ValueError, TypeError):
                continue
        if isinstance(clob_ids, list) and clob_ids and clob_ids[0]:
            return clob_ids[0]
    pytest.skip("No active token found via Gamma API")
    return ""  # unreachable


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def active_token_id() -> str:
    """Fetch one active token_id for the whole module — avoids repeated HTTP calls."""
    return _get_active_token_id()


@pytest.fixture
async def client():
    """Full-stack FastAPI client using ASGITransport.

    We manually enter the app's lifespan context so that the engine is
    initialized before any requests are made, exactly as it would be in
    a real uvicorn process.
    """
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


# ---------------------------------------------------------------------------
# Flow 1: Health + Markets
# ---------------------------------------------------------------------------

class TestHealthAndMarkets:

    @pytest.mark.asyncio
    async def test_health_returns_200(self, client: AsyncClient) -> None:
        resp = await client.get("/api/markets/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "clob" in data

    @pytest.mark.asyncio
    async def test_markets_list_returns_data(self, client: AsyncClient) -> None:
        resp = await client.get("/api/markets/")
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
        assert isinstance(data["data"], list)

    @pytest.mark.asyncio
    async def test_trending_markets(self, client: AsyncClient) -> None:
        resp = await client.get("/api/markets/trending")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_markets_search(self, client: AsyncClient) -> None:
        resp = await client.get("/api/markets/search", params={"q": "bitcoin"})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# Flow 2: Order lifecycle
# ---------------------------------------------------------------------------

class TestOrderLifecycle:

    @pytest.mark.asyncio
    async def test_create_order(self, client: AsyncClient, active_token_id: str) -> None:
        resp = await client.post(
            "/api/orders/create",
            json={"token_id": active_token_id, "side": "BUY", "price": 0.5, "size": 10},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "order" in data

    @pytest.mark.asyncio
    async def test_list_orders(self, client: AsyncClient) -> None:
        resp = await client.get("/api/orders/")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_active_orders(self, client: AsyncClient) -> None:
        resp = await client.get("/api/orders/active")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_portfolio_after_order(self, client: AsyncClient, active_token_id: str) -> None:
        # Place an order first, then check portfolio
        await client.post(
            "/api/orders/create",
            json={"token_id": active_token_id, "side": "BUY", "price": 0.5, "size": 10},
        )
        resp = await client.get("/api/portfolio/")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Flow 3: Strategy lifecycle
# ---------------------------------------------------------------------------

class TestStrategyLifecycle:

    @pytest.mark.asyncio
    async def test_available_strategies(self, client: AsyncClient) -> None:
        resp = await client.get("/api/strategies/available")
        assert resp.status_code == 200
        data = resp.json()
        assert "kernels" in data
        kernels = data["kernels"]
        assert isinstance(kernels, list)
        # At least one of the expected kernels should be present
        assert any(k in kernels for k in ("voice", "market-maker", "signal", "agentic"))

    @pytest.mark.asyncio
    async def test_start_signal_kernel(self, client: AsyncClient, active_token_id: str) -> None:
        resp = await client.post(
            "/api/strategies/start",
            json={"name": "signal", "params": {"token_id": active_token_id, "strategy": "momentum"}},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_strategies(self, client: AsyncClient) -> None:
        resp = await client.get("/api/strategies/")
        assert resp.status_code == 200
        data = resp.json()
        assert "kernels" in data

    @pytest.mark.asyncio
    async def test_stop_signal_kernel(self, client: AsyncClient, active_token_id: str) -> None:
        # Start first, then stop
        await client.post(
            "/api/strategies/start",
            json={"name": "signal", "params": {"token_id": active_token_id, "strategy": "momentum"}},
        )
        resp = await client.post("/api/strategies/stop/signal")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("name") == "signal"

    @pytest.mark.asyncio
    async def test_kernel_stopped_after_stop(self, client: AsyncClient, active_token_id: str) -> None:
        await client.post(
            "/api/strategies/start",
            json={"name": "signal", "params": {"token_id": active_token_id}},
        )
        await client.post("/api/strategies/stop/signal")
        resp = await client.get("/api/strategies/")
        assert resp.status_code == 200
        data = resp.json()
        kernels = data.get("kernels", {})
        signal_kernel = kernels.get("signal", {})
        assert signal_kernel.get("status") in ("stopped", "error", None)


# ---------------------------------------------------------------------------
# Flow 4: Performance + Risk
# ---------------------------------------------------------------------------

class TestPerformanceAndRisk:

    @pytest.mark.asyncio
    async def test_performance_summary(self, client: AsyncClient) -> None:
        resp = await client.get("/api/performance/summary")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_pnl_history(self, client: AsyncClient) -> None:
        resp = await client.get("/api/performance/pnl-history")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_risk_summary(self, client: AsyncClient) -> None:
        resp = await client.get("/api/risk/summary")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_risk_guard_get(self, client: AsyncClient) -> None:
        resp = await client.get("/api/risk/guard")
        assert resp.status_code == 200
        data = resp.json()
        assert "config" in data

    @pytest.mark.asyncio
    async def test_risk_exits_get(self, client: AsyncClient) -> None:
        resp = await client.get("/api/risk/exits")
        assert resp.status_code == 200
        data = resp.json()
        assert "config" in data

    @pytest.mark.asyncio
    async def test_risk_guard_post(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/risk/guard",
            json={"max_stake_per_trade": 100.0, "max_gross_exposure": 5000.0},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_risk_exits_post(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/risk/exits",
            json={"enabled": True, "trailing_stop_pct": 5.0, "expiry_exit_hours": 2.0},
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Flow 5: Backtest
# ---------------------------------------------------------------------------

class TestBacktest:

    @pytest.mark.asyncio
    async def test_run_backtest(self, client: AsyncClient, active_token_id: str) -> None:
        resp = await client.post(
            "/api/backtest/run",
            json={
                "kernel_type": "signal",
                "strategy": "momentum",
                "token_id": active_token_id,
                "prices": [0.5, 0.52, 0.48, 0.55, 0.60, 0.58, 0.62],
                "start_balance": 10000.0,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total_pnl" in data
        assert "pnl_curve" in data

    @pytest.mark.asyncio
    async def test_backtest_requires_5_prices(self, client: AsyncClient, active_token_id: str) -> None:
        resp = await client.post(
            "/api/backtest/run",
            json={
                "kernel_type": "signal",
                "strategy": "momentum",
                "token_id": active_token_id,
                "prices": [0.5, 0.52, 0.48],
            },
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Flow 6: Config
# ---------------------------------------------------------------------------

class TestConfig:

    @pytest.mark.asyncio
    async def test_get_dry_run(self, client: AsyncClient) -> None:
        resp = await client.get("/api/config/dry-run")
        assert resp.status_code == 200
        data = resp.json()
        assert "dry_run" in data
        assert data["dry_run"] is True  # app starts in dry-run mode

    @pytest.mark.asyncio
    async def test_set_dry_run_false(self, client: AsyncClient) -> None:
        resp = await client.post("/api/config/dry-run", params={"enabled": "false"})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_dry_run_state_changes(self, client: AsyncClient) -> None:
        # Disable dry-run
        await client.post("/api/config/dry-run", params={"enabled": "false"})
        resp = await client.get("/api/config/dry-run")
        assert resp.status_code == 200
        data = resp.json()
        assert data["dry_run"] is False

        # Re-enable dry-run to leave things clean
        await client.post("/api/config/dry-run", params={"enabled": "true"})


# ---------------------------------------------------------------------------
# Flow 7: Price history (via markets endpoint)
# ---------------------------------------------------------------------------

class TestPriceHistory:

    @pytest.mark.asyncio
    async def test_market_price_history(self, client: AsyncClient, active_token_id: str) -> None:
        resp = await client.get(f"/api/markets/history/{active_token_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "history" in data
        assert isinstance(data["history"], list)


# ---------------------------------------------------------------------------
# Flow 7b: Backtest history endpoint
# ---------------------------------------------------------------------------

class TestBacktestHistory:

    @pytest.mark.asyncio
    async def test_backtest_history_endpoint(self, client: AsyncClient, active_token_id: str) -> None:
        resp = await client.get(f"/api/backtest/history/{active_token_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "token_id" in data
        assert "prices" in data
        assert "count" in data
        assert isinstance(data["prices"], list)
        assert data["count"] == len(data["prices"])


# ---------------------------------------------------------------------------
# Flow 8: WebSocket
# ---------------------------------------------------------------------------

class TestWebSocket:

    @pytest.mark.asyncio
    async def test_websocket_route_registered(self, client: AsyncClient) -> None:
        """Verify the /ws route is registered in the app's router."""
        from polystation.dashboard.app import create_app as _create_app

        app = _create_app()
        # Collect all routes from the application router
        routes = [getattr(r, "path", None) for r in app.routes]
        assert "/ws" in routes, f"Expected /ws in routes, got: {routes}"

    @pytest.mark.asyncio
    async def test_websocket_via_starlette_client(self) -> None:
        """Use Starlette TestClient (which supports WS) to verify the endpoint works."""
        from starlette.testclient import TestClient
        from polystation.dashboard.app import create_app as _create_app

        app = _create_app()
        with TestClient(app) as tc:
            with tc.websocket_connect("/ws") as ws:
                # Server sends a welcome frame on connect
                data = ws.receive_json()
                assert data.get("type") == "connected"
                # Client sends ping, server replies pong
                ws.send_json({"type": "ping"})
                pong = ws.receive_json()
                assert pong.get("type") == "pong"
