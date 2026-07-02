import pytest
import asyncio
from httpx import AsyncClient

WEBHOOK_URL = "/webhook/whatsapp"

def make_payload(remote_jid, text, from_me=False, is_group=False, push_name="User"):
    return {
        "event": "messages.upsert",
        "instance": "test",
        "data": {
            "key": {
                "remoteJid": remote_jid,
                "fromMe": from_me,
                "id": "test_msg_123",
                "participant": "sender@s.whatsapp.net" if is_group else None
            },
            "message": {
                "conversation": text
            },
            "pushName": push_name
        }
    }

@pytest.mark.asyncio
async def test_text_message(client, mock_gateway, mock_llm, db_session):
    payload = make_payload("12345@s.whatsapp.net", "Hello bot")
    response = await client.post(WEBHOOK_URL, json=payload)
    assert response.status_code == 200

@pytest.mark.asyncio
async def test_image_message(client, mock_gateway, mock_llm):
    payload = {
        "event": "messages.upsert",
        "instance": "test",
        "data": {
            "key": {
                "remoteJid": "12345@s.whatsapp.net",
                "fromMe": False,
                "id": "test_img_123"
            },
            "message": {
                "imageMessage": {
                    "caption": "What is this?"
                }
            },
            "media_data": {
                "mimetype": "image/jpeg",
                "data": "base64data",
                "file_path": "/tmp/test.jpg"
            },
            "pushName": "User"
        }
    }
    response = await client.post(WEBHOOK_URL, json=payload)
    assert response.status_code == 200

@pytest.mark.asyncio
async def test_group_message(client, mock_gateway, mock_llm):
    payload = make_payload("12345-6789@g.us", "Hello group", is_group=True)
    response = await client.post(WEBHOOK_URL, json=payload)
    assert response.status_code == 200

@pytest.mark.asyncio
async def test_command_message(client, mock_gateway, mock_llm):
    payload = make_payload("12345-6789@g.us", "!help", is_group=True)
    response = await client.post(WEBHOOK_URL, json=payload)
    assert response.status_code == 200
