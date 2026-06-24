import asyncio
from sqlalchemy.orm import Session
from app.state import SessionLocal, get_chat_settings
from app.commands import handle_command
from unittest.mock import AsyncMock, patch, MagicMock

async def test():
    db = SessionLocal()
    # Mock send_text_message
    with patch("app.commands.send_text_message", new_callable=AsyncMock) as mock_send:
        # Chat ID for DM ends with @s.whatsapp.net
        chat_id = "12345@s.whatsapp.net"
        sender_id = "12345@s.whatsapp.net"
        
        try:
            print("Calling handle_command...")
            await handle_command("!claim_ownership", chat_id, sender_id, db)
            print("handle_command finished.")
            print("Mock send calls:", mock_send.call_args_list)
        except Exception as e:
            print("Exception raised!", e)

if __name__ == "__main__":
    asyncio.run(test())
