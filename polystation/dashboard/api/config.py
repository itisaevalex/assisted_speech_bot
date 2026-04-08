"""Configuration endpoints — dry-run toggle and runtime settings."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from polystation.dashboard.app import get_engine
from polystation.dashboard.auth import require_auth
from polystation.dashboard.rate_limit import rate_limit

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/dry-run", summary="Set dry-run mode",
             dependencies=[Depends(require_auth)])
async def set_dry_run(enabled: bool = True) -> dict[str, Any]:
    """Enable or disable dry-run mode on the execution engine.

    When dry-run is active no real orders are submitted to the CLOB.
    Pass ``?enabled=false`` to switch to live trading.
    """
    eng = get_engine()
    eng.execution.set_dry_run(enabled)
    logger.info("Dry-run mode set to %s", enabled)
    return {"dry_run": enabled}


@router.get("/dry-run", summary="Get current dry-run state")
def get_dry_run() -> dict[str, Any]:
    """Return the current dry-run flag from the execution engine."""
    eng = get_engine()
    return {"dry_run": eng.execution._dry_run}


class CredentialsRequest(BaseModel):
    host: str = "https://clob.polymarket.com"
    pk: str = ""
    pbk: str = ""
    clob_api_key: str = ""
    clob_secret: str = ""
    clob_pass_phrase: str = ""


@router.post("/credentials", summary="Set API credentials and initialize trading client",
             dependencies=[Depends(require_auth), Depends(rate_limit(3, 60))])
async def set_credentials(req: CredentialsRequest) -> dict[str, Any]:
    """Set CLOB credentials in the running process and reinitialize the execution engine.

    This sets os.environ vars so that create_clob_client() picks them up,
    then rebuilds the execution engine's CLOB client.
    """
    import os
    from polystation.exchanges.polymarket import PolymarketExchange
    from polystation.trading.execution import ExecutionEngine

    # Set env vars for this process
    os.environ["HOST"] = req.host
    if req.pk:
        os.environ["PK"] = req.pk
    if req.pbk:
        os.environ["PBK"] = req.pbk
    if req.clob_api_key:
        os.environ["CLOB_API_KEY"] = req.clob_api_key
    if req.clob_secret:
        os.environ["CLOB_SECRET"] = req.clob_secret
    if req.clob_pass_phrase:
        os.environ["CLOB_PASS_PHRASE"] = req.clob_pass_phrase

    # Build and connect the PolymarketExchange adapter with the provided credentials.
    try:
        poly_exchange = PolymarketExchange(
            host=req.host,
            private_key=req.pk or None,
            api_key=req.clob_api_key or None,
            api_secret=req.clob_secret or None,
            api_passphrase=req.clob_pass_phrase or None,
        )
        await poly_exchange.connect()

        eng = get_engine()
        # Disconnect the previous exchange adapter if one is registered.
        existing = eng.get_exchange("polymarket")
        if existing is not None:
            await existing.disconnect()

        eng.register_exchange(poly_exchange)
        eng.execution = ExecutionEngine(poly_exchange, eng.orders, eng.portfolio)
        eng.execution.set_dry_run(False)

        logger.info("Credentials set — live PolymarketExchange initialized")
        return {"status": "ok", "dry_run": False, "host": req.host}
    except Exception as exc:
        logger.error("Failed to initialize PolymarketExchange: %s", exc)
        return {"status": "error", "error": "Failed to initialize exchange. Check server logs."}
