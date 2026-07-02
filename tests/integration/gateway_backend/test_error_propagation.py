import pytest
import asyncio
from unittest.mock import AsyncMock

WEBHOOK_URL = "/webhook/whatsapp"

def make_payload(text):
    return {
        "event": "messages.upsert",
        "instance": "test",
        "data": {
            "key": {
                "remoteJid": "12345@s.whatsapp.net",
                "fromMe": False,
                "id": "test_msg_err",
            },
            "message": {
                "conversation": text
            },
            "pushName": "User"
        }
    }

@pytest.mark.asyncio
async def test_gateway_500_error(client, mock_gateway, mock_llm):
    from app.whatsapp_gateway import GatewaySendResult
    mock_gateway['send'].return_value = GatewaySendResult(success=False, status_code=500, error_code="INTERNAL_ERROR")
    
    payload = make_payload("Hello bot")
    response = await client.post(WEBHOOK_URL, json=payload)
    assert response.status_code == 200

@pytest.mark.asyncio
async def test_gateway_timeout(client, mock_gateway, mock_llm):
    mock_gateway['send'].side_effect = Exception("Timeout")
    
    payload = make_payload("Hello bot")
    response = await client.post(WEBHOOK_URL, json=payload)
    assert response.status_code == 200

@pytest.mark.asyncio
async def test_llm_500_error(client, mock_gateway, mock_llm):
    mock_llm.side_effect = Exception("LLM Error")
    
    payload = make_payload("Hello bot")
    response = await client.post(WEBHOOK_URL, json=payload)
    assert response.status_code == 200

@pytest.mark.asyncio
async def test_invalid_payload(client):
    response = await client.post(WEBHOOK_URL, json={"event": "messages.upsert"})
    assert response.status_code == 422

@pytest.mark.asyncio
async def test_unsupported_event(client):
    response = await client.post(WEBHOOK_URL, json={
        "event": "messages.update",
        "instance": "test",
        "data": {
            "key": {"remoteJid": "123", "fromMe": False, "id": "1"},
            "message": {"conversation": "test"}
        }
    })
    assert response.status_code == 200
