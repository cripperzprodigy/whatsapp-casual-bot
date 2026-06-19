"""
Unit tests for the 16-issue critical refactor.
Per SOP: agents must write tests for all new logic introduced.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ------------------------------------------------------------------ #
# Issue 1 — Webhook schema accepts missing `instance` field
# ------------------------------------------------------------------ #

class TestWebhookSchema:
    """
    Validates that WhatsAppWebhookPayload no longer requires
    the `instance` field (fix for HTTP 422 blocker).
    """

    def _minimal_payload(self, include_instance: bool = False) -> dict:
        payload = {
            "event": "messages.upsert",
            "data": {
                "key": {
                    "remoteJid": "1234567890@g.us",
                    "fromMe": False,
                    "id": "ABCDEF123",
                    "participant": None,
                },
                "message": {"conversation": "Hello"},
                "pushName": "Test User",
            },
        }
        if include_instance:
            payload["instance"] = "whatsapp-web-js"
        return payload

    def test_webhook_accepts_no_instance(self):
        """Issue 1: payload without instance must NOT raise."""
        from app.whatsapp_gateway import WhatsAppWebhookPayload

        payload = self._minimal_payload(include_instance=False)
        model = WhatsAppWebhookPayload(**payload)
        assert model.instance is None
        assert model.event == "messages.upsert"

    def test_webhook_accepts_with_instance(self):
        """Issue 1: payload WITH instance must still work."""
        from app.whatsapp_gateway import WhatsAppWebhookPayload

        payload = self._minimal_payload(include_instance=True)
        model = WhatsAppWebhookPayload(**payload)
        assert model.instance == "whatsapp-web-js"

    def test_webhook_rejects_missing_event(self):
        """Issue 1: truly malformed payloads must still fail."""
        from app.whatsapp_gateway import WhatsAppWebhookPayload
        from pydantic import ValidationError

        payload = self._minimal_payload()
        del payload["event"]  # remove required field
        with pytest.raises(ValidationError):
            WhatsAppWebhookPayload(**payload)


# ------------------------------------------------------------------ #
# Issue 2 — Buffer pruning with while loop
# ------------------------------------------------------------------ #

class TestBufferPrune:
    """
    Validates that the message buffer never exceeds MESSAGE_BUFFER_SIZE
    even when multiple messages arrive in a burst.
    """

    def _make_db(self, existing_count: int):
        """Build a mock DB session with `existing_count` messages."""
        # Fake oldest message to delete
        fake_msg = MagicMock()

        # Counter that decrements as deletes happen
        counter = {"value": existing_count}

        def fake_count():
            return counter["value"]

        def fake_delete(obj):
            counter["value"] -= 1

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.count.side_effect = fake_count
        mock_query.order_by.return_value = mock_query
        mock_query.first.return_value = fake_msg

        db = MagicMock()
        db.query.return_value = mock_query
        db.delete.side_effect = fake_delete
        return db, counter

    def test_buffer_prune_single_overflow(self):
        """Issue 2: overflow by 1 — exactly one delete."""
        from app.state import add_message_to_buffer
        from unittest.mock import patch

        with patch("app.state.settings") as mock_settings:
            mock_settings.MESSAGE_BUFFER_SIZE = 5
            db, counter = self._make_db(existing_count=6)
            add_message_to_buffer(
                db, "chat1", "sender1", "Alice", "hello"
            )
            assert counter["value"] == 5

    def test_buffer_prune_burst_overflow(self):
        """Issue 2: overflow by 10 — all 10 must be pruned."""
        from app.state import add_message_to_buffer
        from unittest.mock import patch

        with patch("app.state.settings") as mock_settings:
            mock_settings.MESSAGE_BUFFER_SIZE = 5
            db, counter = self._make_db(existing_count=15)
            add_message_to_buffer(
                db, "chat1", "sender1", "Alice", "hello"
            )
            assert counter["value"] == 5

    def test_buffer_no_prune_when_under_limit(self):
        """Issue 2: no delete when buffer is within bounds."""
        from app.state import add_message_to_buffer
        from unittest.mock import patch

        with patch("app.state.settings") as mock_settings:
            mock_settings.MESSAGE_BUFFER_SIZE = 200
            db, counter = self._make_db(existing_count=10)
            add_message_to_buffer(
                db, "chat1", "sender1", "Alice", "hello"
            )
            assert db.delete.call_count == 0


# ------------------------------------------------------------------ #
# Issue 3 — Language detection robustness
# ------------------------------------------------------------------ #

class TestLanguageDetection:
    """
    Validates that detect_language correctly normalises LLM output
    that contains whitespace or full language names.
    """

    @pytest.mark.asyncio
    async def test_strips_whitespace(self):
        """Issue 3: ' en ' (with spaces) must return 'en'."""
        with patch(
            "app.translation.ask_llm", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = " en "
            from app.translation import detect_language
            result = await detect_language("Hello world")
            assert result == "en"

    @pytest.mark.asyncio
    async def test_full_name_english(self):
        """Issue 3: 'English' must map to 'en'."""
        with patch(
            "app.translation.ask_llm", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = "English"
            from app.translation import detect_language
            result = await detect_language("Hello world")
            assert result == "en"

    @pytest.mark.asyncio
    async def test_full_name_indonesian(self):
        """Issue 3: 'Indonesian' must map to 'id'."""
        with patch(
            "app.translation.ask_llm", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = "Indonesian"
            from app.translation import detect_language
            result = await detect_language("Halo dunia")
            assert result == "id"

    @pytest.mark.asyncio
    async def test_unknown_returned_for_gibberish(self):
        """Issue 3: truly unrecognisable output must return 'unknown'."""
        with patch(
            "app.translation.ask_llm", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = "some random verbose response"
            from app.translation import detect_language
            result = await detect_language("???")
            assert result == "unknown"

    @pytest.mark.asyncio
    async def test_valid_two_letter_code(self):
        """Issue 3: clean two-letter code must pass through unchanged."""
        with patch(
            "app.translation.ask_llm", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = "id"
            from app.translation import detect_language
            result = await detect_language("Halo")
            assert result == "id"


# ------------------------------------------------------------------ #
# Issue 15 — !task done input validation
# ------------------------------------------------------------------ #

class TestTaskDoneInput:
    """
    Validates that !task done with a non-integer argument returns a
    friendly error message instead of crashing.
    """

    @pytest.mark.asyncio
    async def test_task_done_with_invalid_id_sends_friendly_message(
        self,
    ):
        """Issue 15: '!task done abc' must NOT raise ValueError."""
        with (
            patch(
                "app.commands.send_text_message",
                new_callable=AsyncMock,
            ) as mock_send,
            patch(
                "app.commands.get_chat_settings"
            ) as mock_settings,
        ):
            mock_settings.return_value = MagicMock(
                ignored_languages=None,
                auto_translate_enabled=None,
                default_target_language=None,
            )
            from app.commands import handle_command

            db = MagicMock()
            await handle_command(
                "!task done abc", "chat1", "sender1", db
            )

            # Should send a user-friendly error, not raise
            mock_send.assert_called_once()
            call_args = mock_send.call_args[0]
            assert "invalid" in call_args[1].lower() or \
                   "numeric" in call_args[1].lower() or \
                   "id" in call_args[1].lower()

    @pytest.mark.asyncio
    async def test_task_done_with_valid_id_does_not_error(self):
        """Issue 15: '!task done 3' with a valid integer must work."""
        with (
            patch(
                "app.commands.send_text_message",
                new_callable=AsyncMock,
            ) as mock_send,
            patch(
                "app.commands.get_chat_settings"
            ) as mock_chat_settings,
        ):
            mock_chat_settings.return_value = MagicMock(
                ignored_languages=None,
                auto_translate_enabled=None,
                default_target_language=None,
            )
            fake_task = MagicMock()
            fake_task.id = 3

            db = MagicMock()
            db.query.return_value.filter.return_value.first.return_value = (
                fake_task
            )

            from app.commands import handle_command

            await handle_command(
                "!task done 3", "chat1", "sender1", db
            )
            # Should call send with "marked as done"
            mock_send.assert_called_once()
            assert "done" in mock_send.call_args[0][1].lower()
