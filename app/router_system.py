import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from app.config import settings
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/whatsapp/qr", response_class=HTMLResponse)
async def get_whatsapp_qr():
    """Proxies the QR code from the internal Node.js Gateway"""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{settings.WHATSAPP_GATEWAY_URL}/whatsapp/qr")
            return HTMLResponse(content=resp.text, status_code=resp.status_code)
    except Exception as e:
        logger.error(f"Error fetching QR: {e}")
        raise HTTPException(status_code=500, detail="Could not reach the internal WhatsApp Gateway.")

@router.get("/whatsapp/status")
async def get_whatsapp_status():
    """Proxies status check to internal Gateway"""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{settings.WHATSAPP_GATEWAY_URL}/whatsapp/status")
            return resp.json()
    except Exception as e:
        logger.error(f"Error fetching status: {e}")
        raise HTTPException(status_code=500, detail="Could not reach the internal WhatsApp Gateway.")

@router.post("/whatsapp/reset-session")
async def reset_whatsapp_session():
    """Tells the internal Node.js Gateway to wipe its session data and generate a new QR."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{settings.WHATSAPP_GATEWAY_URL}/whatsapp/reset-session")
            return resp.json()
    except Exception as e:
        logger.error(f"Error resetting session: {e}")
        raise HTTPException(status_code=500, detail="Could not reach the internal WhatsApp Gateway.")
