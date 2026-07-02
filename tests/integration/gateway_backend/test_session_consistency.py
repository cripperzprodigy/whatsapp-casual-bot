import pytest
import asyncio
from httpx import AsyncClient

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
async def test_isolated_user_sessions(client, mock_gateway, mock_llm):
    payload_a = make_payload("user_a@s.whatsapp.net", "Hi I am A")
    resp_a = await client.post(WEBHOOK_URL, json=payload_a)
    assert resp_a.status_code == 200
    
    payload_b = make_payload("user_b@s.whatsapp.net", "Hi I am B")
    resp_b = await client.post(WEBHOOK_URL, json=payload_b)
    assert resp_b.status_code == 200

@pytest.mark.asyncio
async def test_group_vs_dm_isolation(client, mock_gateway, mock_llm):
    payload_group = make_payload("group@g.us", "Random chat")
    payload_group["data"]["key"]["participant"] = "user_a@s.whatsapp.net"
    resp_group = await client.post(WEBHOOK_URL, json=payload_group)
    assert resp_group.status_code == 200
    
    payload_dm = make_payload("user_a@s.whatsapp.net", "Private chat")
    resp_dm = await client.post(WEBHOOK_URL, json=payload_dm)
    assert resp_dm.status_code == 200

@pytest.mark.asyncio
async def test_session_state_persistence(client, mock_gateway, db_session):
    payload = make_payload("user_persistence@s.whatsapp.net", "Save me")
    response = await client.post(WEBHOOK_URL, json=payload)
    assert response.status_code == 200
