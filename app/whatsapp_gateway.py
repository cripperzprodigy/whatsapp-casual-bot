import httpx
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from app.config import settings
import logging

logger = logging.getLogger(__name__)

# Expected Webhook Payload schemas (Approximated for Evolution API / Baileys)
class WebhookMessage(BaseModel):
    remoteJid: str # chat ID
    fromMe: bool
    id: str
    participant: Optional[str] = None # Sender in a group

class WebhookMessageContent(BaseModel):
    conversation: Optional[str] = None
    extendedTextMessage: Optional[Dict[str, Any]] = None

class WebhookData(BaseModel):
    message: WebhookMessageContent
    key: WebhookMessage
    pushName: Optional[str] = None

class WhatsAppWebhookPayload(BaseModel):
    event: str
    instance: str
    data: WebhookData

async def fetch_group_metadata(chat_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetches group metadata to check the group name, members, and admin status from internal gateway.
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

async def send_text_message(chat_id: str, text: str, reply_to_msg_id: Optional[str] = None) -> bool:
    """
    Sends a text message back to the WhatsApp group via the internal gateway HTTP API.
    Optionally quotes/replies to an original message if `reply_to_msg_id` is provided.
    """
    url = f"{settings.WHATSAPP_GATEWAY_URL}/message/sendText"
    
    payload = {
        "number": chat_id,
        "textMessage": {
            "text": text
        }
    }
    
    if reply_to_msg_id:
        # In our webhook schema, msg_key.id is just the string ID of the message.
        # But whatsapp-web.js requires the fully serialized ID.
        # For incoming messages, the serialized ID format is usually `false_<chat_id>_<msg_id>`.
        # We construct it based on typical Baileys/whatsapp-web.js formats.
        serialized_id = f"false_{chat_id}_{reply_to_msg_id}"
        payload["options"] = {"quoted": serialized_id}
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            logger.info(f"Message sent successfully to {chat_id}")
            return True
    except Exception as e:
        logger.error(f"Failed to send message to {chat_id}: {e}")
        return False
