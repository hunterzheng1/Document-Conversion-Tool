"""BI-05: Telegram 适配器（TelegramAdapter）测试。"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from docconv.integrations.telegram.adapter import TelegramAdapter
from docconv.integrations.common import BotMessage, BotPlatform
from docconv.infra.bot_error_codes import BotErrorCodes


@pytest.fixture()
def adapter():
    return TelegramAdapter(
        bot_token="test_bot_token_12345",
        allowed_chats={"chat_123", "chat_456"},
        webhook_secret="secret_abc",
    )


class TestVerifySource:
    """webhook 来源验证测试。"""

    def test_valid_secret(self, adapter):
        assert adapter.verify_source({"secret_token": "secret_abc"}) is True

    def test_invalid_secret(self, adapter):
        assert adapter.verify_source({"secret_token": "wrong_secret"}) is False

    def test_no_secret_configured(self):
        adapter = TelegramAdapter(bot_token="test", webhook_secret="")
        assert adapter.verify_source({"any": "data"}) is True


class TestAllowlist:
    """allowlist 检查测试。"""

    def test_allowed_chat(self, adapter):
        allowed, reason = adapter.check_allowlist("chat_123")
        assert allowed is True

    def test_denied_chat(self, adapter):
        allowed, reason = adapter.check_allowlist("chat_999")
        assert allowed is False
        assert reason != ""


class TestParseMessage:
    """消息解析测试。"""

    def test_parse_text_message(self, adapter):
        payload = {
            "update_id": 12345,
            "message": {
                "chat": {"id": 123},
                "from": {"id": 456},
                "text": "/convert",
            },
        }
        msg = adapter.parse_message(payload)
        assert msg.platform == BotPlatform.TELEGRAM.value
        assert msg.external_message_id == "12345"
        assert msg.chat_id == "123"
        assert msg.sender_id == "456"
        assert msg.instruction == "/convert"

    def test_parse_document_message(self, adapter):
        payload = {
            "update_id": 67890,
            "message": {
                "chat": {"id": 789},
                "from": {"id": 101},
                "document": {
                    "file_id": "AgACAgEAAx...",
                    "file_name": "report.pdf",
                },
                "caption": "/convert 敏感模式",
            },
        }
        msg = adapter.parse_message(payload)
        assert msg.file_id == "AgACAgEAAx..."
        assert msg.filename == "report.pdf"
        assert msg.instruction == "/convert 敏感模式"

    def test_parse_no_message_raises(self, adapter):
        with pytest.raises(ValueError, match="无 message"):
            adapter.parse_message({"update_id": 1})

    def test_parse_no_chat_id_raises(self, adapter):
        with pytest.raises(ValueError, match="无 chat"):
            adapter.parse_message({
                "update_id": 1,
                "message": {"from": {"id": 1}},
            })


class TestInstructionParsing:
    """指令解析集成测试。"""

    def test_parse_convert(self, adapter):
        result = adapter.parse_instruction("/convert 敏感模式")
        assert result.action == "convert"
        assert result.options.get("sensitive_mode") is True

    def test_parse_help(self, adapter):
        result = adapter.parse_instruction("/help")
        assert result.action == "help"

    def test_parse_unknown(self, adapter):
        result = adapter.parse_instruction("random text")
        assert result.rejected is True


class TestSendResult:
    """结果回传测试。"""

    @pytest.mark.asyncio
    async def test_send_text_result(self, adapter):
        with patch.object(adapter.client, "send_message", new_callable=AsyncMock) as mock:
            mock.return_value = {}
            await adapter.send_result("chat_123", "转换完成")
            mock.assert_called_once_with("chat_123", "转换完成")

    @pytest.mark.asyncio
    async def test_send_file_result(self, adapter):
        with patch.object(adapter.client, "send_document", new_callable=AsyncMock) as mock:
            mock.return_value = {}
            await adapter.send_result("chat_123", "", "/path/to/result.md")
            mock.assert_called_once_with("chat_123", "/path/to/result.md", caption="转换完成！")


class TestSendFailure:
    """失败通知测试。"""

    @pytest.mark.asyncio
    async def test_send_failure_message(self, adapter):
        with patch.object(adapter.client, "send_message", new_callable=AsyncMock) as mock:
            mock.return_value = {}
            await adapter.send_failure("chat_123", "job_20260101_abc12345", "超时")
            mock.assert_called_once()
            call_args = mock.call_args
            assert "abc12345" in call_args[0][1]
            assert "超时" in call_args[0][1]
