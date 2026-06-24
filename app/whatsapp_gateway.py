import httpx
from pydantic import BaseModel
from typing import Optional, Dict, Any
from app.config import settings
import logging

# Issue 7: named constant — incoming msgs serialized as
# 'false_<chat_id>_<msg_id>' in whatsapp-web.js
_INCOMING_MSG_PREFIX = "false_"

logger = logging.getLogger(__name__)

# WISP Schemas
class GatewaySendResult(BaseModel):
    success: bool
    status_code: int
    queued: bool = False
    error_code: Optional[str] = None
    requires_qr: bool = False
    message: Optional[str] = None

    def __bool__(self):
        return self.success

class DeliveryResponse(BaseModel):
    status: str
    message_id: Optional[str] = None
    error_code: Optional[str] = None
    error: Optional[str] = None
    reason: Optional[str] = None
    requires_qr: Optional[bool] = False
    recovery_tier: Optional[int] = 0
    message: Optional[str] = None

# Expected Webhook Payload schemas (Approximated for Evolution API / Baileys)
class WebhookMessage(BaseModel):
    remoteJid: str # chat ID
    fromMe: bool
    id: str
    participant: Optional[str] = None # Sender in a group

class WebhookMessageContent(BaseModel):
    conversation: Optional[str] = None
    extendedTextMessage: Optional[Dict[str, Any]] = None
    contextInfo: Optional[Dict[str, Any]] = None

class WebhookData(BaseModel):
    message: WebhookMessageContent
    key: WebhookMessage
    pushName: Optional[str] = None
    media_data: Optional[Dict[str, Any]] = None

class WhatsAppWebhookPayload(BaseModel):
    event: str
    # Issue 1: Optional — Node.js gateway does not send this field;
    # made optional to prevent HTTP 422 on every incoming webhook.
    instance: Optional[str] = None
    data: WebhookData

async def check_gateway_health() -> Dict[str, Any]:
    """
    Checks the health of the Node.js WhatsApp Gateway.
    Returns the JSON response from /whatsapp/recovery-status
    """
    url = f"{settings.WHATSAPP_GATEWAY_URL}/whatsapp/recovery-status"
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=5.0)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.error(f"Failed to fetch gateway health: {e}")
        return {"isConnected": False, "recoveryTier": -1, "consecutiveFailures": 99}

async def fetch_group_metadata(
    chat_id: str,
) -> Optional[Dict[str, Any]]:
    """
    Fetches group metadata to check the group name, members,
    and admin status from internal gateway.
    """
    url = f"{settings.WHATSAPP_GATEWAY_URL}/group/findGroupInfos"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params={"groupJid": chat_id})
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.error(f"Failed to fetch group metadata for {chat_id}: {e}")
        return None

async def send_text_message(
    chat_id: str,
    text: str,
    reply_to_msg_id: Optional[str] = None,
    quoted_participant: Optional[str] = None,
) -> GatewaySendResult:
    """
    Sends a text message back to the WhatsApp group via the
    internal gateway HTTP API. Optionally quotes/replies to an
    original message if `reply_to_msg_id` is provided.
    """
    url = f"{settings.WHATSAPP_GATEWAY_URL}/message/sendText"
    
    payload = {
        "number": chat_id,
        "textMessage": {
            "text": text
        }
    }
    
    if reply_to_msg_id:
        payload["quotedMsgId"] = reply_to_msg_id
    
    import asyncio
    max_retries = 3
    base_delay = 2
    
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload)

                # Check for 202 Accepted (Queued for Recovery)
                if response.status_code == 202:
                    resp_data = DeliveryResponse(**response.json())
                    reason = resp_data.reason or resp_data.error_code
                    logger.warning(f"Command response queued by gateway for {chat_id}. User may not see immediate reply. Reason: {reason}")
                    
                    if reason == "CLIENT_SETTLING":
                        # Increase wait time to 6s before retry, wait longer than settling period
                        logger.info(f"Client is settling. Delaying retry for 6 seconds...")
                        await asyncio.sleep(6)
                        continue
                        
                    return GatewaySendResult(
                        success=False,
                        status_code=202,
                        queued=True,
                        error_code=reason,
                        message=resp_data.message
                    )

                response.raise_for_status()
                logger.info(f"Message sent successfully to {chat_id}")
                return GatewaySendResult(
                    success=True,
                    status_code=200
                )
        except httpx.HTTPStatusError as e:
            if e.response.status_code in [500, 503]:
                try:
                    error_data = e.response.json()
                    
                    # If 503 NOT_READY, abort immediate retry and queue
                    if e.response.status_code == 503 and error_data.get("status") == "NOT_READY":
                        logger.error("Gateway reported NOT_READY. Aborting immediate retry and queuing.")
                        return GatewaySendResult(success=False, status_code=503, queued=True, error_code="NOT_READY")
                        
                    resp_data = DeliveryResponse(**error_data)
                    requires_qr = resp_data.requires_qr
                    if requires_qr:
                        logger.critical(f"CRITICAL: WhatsApp session requires QR scan! Pausing message queue for {chat_id}. Notify admin immediately.")
                        return GatewaySendResult(
                            success=False,
                            status_code=e.response.status_code,
                            error_code=resp_data.error_code,
                            requires_qr=True,
                            message=resp_data.error
                        )
                    # If 503 but no QR required yet (e.g. initial validateSession fail), we could fail fast or retry
                    if e.response.status_code == 503 and resp_data.error_code == "SESSION_CORRUPT":
                        logger.error(f"Gateway reported SESSION_CORRUPT for {chat_id}. Attempting to wait for recovery...")
                except Exception as ex:
                    logger.error(f"Failed to parse error response: {ex}")
            
            delay = base_delay * (2 ** attempt)
            logger.warning(f"HTTPStatusError sending message to {chat_id} (Attempt {attempt+1}/{max_retries}). Retrying in {delay}s...")
            await asyncio.sleep(delay)
        except Exception as e:
            delay = base_delay * (2 ** attempt)
            logger.warning(f"Failed to send message to {chat_id} (Attempt {attempt+1}/{max_retries}): {e}. Retrying in {delay}s...")
            await asyncio.sleep(delay)
            
    logger.error(f"Exhausted retries. Failed to send message to {chat_id}")
    return GatewaySendResult(
        success=False,
        status_code=500,
        error_code="SEND_TIMEOUT",
        message="Exhausted retries"
    )
