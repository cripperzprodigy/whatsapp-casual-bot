import httpx
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.config import settings
from app.state import get_db
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/whatsapp/qr", response_class=HTMLResponse)
async def get_whatsapp_qr() -> HTMLResponse:
    """Proxies the QR code from the internal Node.js Gateway."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{settings.WHATSAPP_GATEWAY_URL}/whatsapp/qr"
            )
            return HTMLResponse(
                content=resp.text, status_code=resp.status_code
            )
    except Exception as exc:
        logger.error("Error fetching QR: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Could not reach the internal WhatsApp Gateway.",
        )


@router.get("/whatsapp/status")
async def get_whatsapp_status() -> dict:
    """Proxies status check to internal Gateway."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{settings.WHATSAPP_GATEWAY_URL}/whatsapp/status"
            )
            return resp.json()
    except Exception as exc:
        logger.error("Error fetching status: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Could not reach the internal WhatsApp Gateway.",
        )


@router.post("/whatsapp/reset-session")
async def reset_whatsapp_session() -> dict:
    """Tells the Node.js Gateway to wipe its session and re-QR."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{settings.WHATSAPP_GATEWAY_URL}/whatsapp/reset-session"
            )
            return resp.json()
    except Exception as exc:
        logger.error("Error resetting session: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Could not reach the internal WhatsApp Gateway.",
        )


# Issue 9: health check endpoint for container orchestration
@router.get("/health")
async def health_check(db: Session = Depends(get_db)) -> JSONResponse:
    """
    Checks liveness of the Python API, SQLite DB, and the Node.js
    Gateway. Returns HTTP 200 if all healthy, 503 otherwise.
    """
    health: dict = {
        "status": "ok",
        "db": "ok",
        "gateway": "ok",
    }
    http_status = 200

    # DB check — run a trivial query
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        logger.error("Health check: DB error: %s", exc)
        health["db"] = f"error: {exc}"
        health["status"] = "degraded"
        http_status = 503

    # Gateway check — lightweight status ping
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(
                f"{settings.WHATSAPP_GATEWAY_URL}/whatsapp/status"
            )
            if resp.status_code != 200:
                health["gateway"] = f"http_{resp.status_code}"
                health["status"] = "degraded"
                http_status = 503
    except Exception as exc:
        logger.warning("Health check: Gateway unreachable: %s", exc)
        health["gateway"] = "unreachable"
        health["status"] = "degraded"
        http_status = 503

    return JSONResponse(content=health, status_code=http_status)
