import pytest
import asyncio
from unittest.mock import AsyncMock

WEBHOOK_URL = "/webhook/whatsapp"

def make_payload(remote_jid, text):
    return {
        "event": "messages.upsert",
        "instance": "test",
        "data": {
            "key": {
                "remoteJid": remote_jid,
                "fromMe": False,
                "id": f"msg_{remote_jid}_123",
            },
            "message": {
                "conversation": text
            },
            "pushName": "User"
        }
    }

@pytest.mark.asyncio
async def test_rag_search_command(client, mock_gateway, mock_search):
    payload = make_payload("user_rag@s.whatsapp.net", "!search python fastAPI tutorials")
    resp = await client.post(WEBHOOK_URL, json=payload)
    assert resp.status_code == 200

@pytest.mark.asyncio
async def test_deep_search_command(client, mock_gateway, mock_search):
    payload = make_payload("user_rag@s.whatsapp.net", "!deepsearch advanced python concepts")
    resp = await client.post(WEBHOOK_URL, json=payload)
    assert resp.status_code == 200

@pytest.mark.asyncio
async def test_agentic_tool_call(client, mock_gateway, mock_search):
    payload = make_payload("user_rag@s.whatsapp.net", "What is the latest news about AI?")
    resp = await client.post(WEBHOOK_URL, json=payload)
    assert resp.status_code == 200
