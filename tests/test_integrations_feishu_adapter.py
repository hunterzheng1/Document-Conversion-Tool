"""BI-08: 飞书适配器（FeishuAdapter）测试。"""

import json
import pytest
from unittest.mock import AsyncMock, patch

from docconv.integrations.feishu.adapter import FeishuAdapter
from docconv.integrations.common import BotMessage, BotPlatform
from docconv.infra.bot_error_codes import BotErrorCodes


@pytest.fixture()
def adapter():
    return FeishuAdapter(
        app_id="cli_test_app",
        app_secret="test_secret_1234567890",
        allowed_tenants={"tenant_abc"},
        verification_token="verify_token_xyz",
    )


class TestVerifySource:
    """来源验证测试。"""

    def test_challenge_valid(self, adapter):
        """challenge 验证事件 token 正确时应通过。"""
        payload = {
            "type": "url_verification",
            "token": "verify_token_xyz",
            "challenge": "test_challenge_123",
        }
        assert adapter.verify_source(payload) is True

    def test_challenge_invalid(self, adapter):
        """challenge 验证事件 token 错误时应拒绝。"""
        payload = {
            "type": "url_verification",
            "token": "wrong_token",
            "challenge": "test_challenge_123",
        }
        assert adapter.verify_source(payload) is False

    def test_message_event_valid_token(self, adapter):
        """消息事件 token 正确时应通过。"""
        payload = {
            "header": {"token": "verify_token_xyz"},
            "event": {},
        }
        assert adapter.verify_source(payload) is True

    def test_message_event_invalid_token(self, adapter):
        """消息事件 token 错误时应拒绝。"""
        payload = {
            "header": {"token": "wrong_token"},
            "event": {},
        }
        assert adapter.verify_source(payload) is False

    def test_no_verification_token_configured(self):
        """未配置 verification_token 时应通过。"""
        adapter = FeishuAdapter(app_id="x", app_secret="y", verification_token="")
        payload = {"header": {}, "event": {}}
        assert adapter.verify_source(payload) is True


class TestAllowlist:
    """allowlist 检查测试。"""

    def test_allowed_tenant(self, adapter):
        allowed, reason = adapter.check_allowlist("tenant_abc")
        assert allowed is True

    def test_denied_tenant(self, adapter):
        allowed, reason = adapter.check_allowlist("tenant_xyz")
        assert allowed is False


class TestParseMessage:
    """消息解析测试。"""

    def test_parse_text_message(self, adapter):
        payload = {
            "event": {
                "message": {
                    "chat_id": "oc_test_chat",
                    "message_id": "om_test_001",
                    "message_type": "text",
                    "content": json.dumps({"text": "/convert"}),
                },
                "sender": {
                    "sender_id": {"open_id": "ou_test_user"},
                },
            },
        }
        msg = adapter.parse_message(payload)
        assert msg.platform == BotPlatform.FEISHU.value
        assert msg.external_message_id == "om_test_001"
        assert msg.chat_id == "oc_test_chat"
        assert msg.sender_id == "ou_test_user"
        assert msg.instruction == "/convert"

    def test_parse_file_message(self, adapter):
        payload = {
            "event": {
                "message": {
                    "chat_id": "oc_test_chat",
                    "message_id": "om_test_002",
                    "message_type": "file",
                    "content": json.dumps({
                        "file_key": "file_key_123",
                        "file_name": "report.pdf",
                    }),
                },
                "sender": {
                    "sender_id": {"open_id": "ou_test_user"},
                },
            },
        }
        msg = adapter.parse_message(payload)
        assert msg.file_id == "file_key_123"
        assert msg.filename == "report.pdf"
        assert msg.instruction == "/convert"  # 文件消息自动设为 /convert

    def test_parse_no_chat_id_raises(self, adapter):
        with pytest.raises(ValueError, match="无 chat_id"):
            adapter.parse_message({
                "event": {"message": {}, "sender": {}},
            })


class TestHandleChallenge:
    """challenge 验证处理测试。"""

    def test_handle_challenge(self, adapter):
        payload = {
            "challenge": "test_challenge_value",
            "type": "url_verification",
        }
        response = adapter.handle_challenge(payload)
        assert response == {"challenge": "test_challenge_value"}


class TestCheckFileType:
    """文件类型检查测试。"""

    def test_pdf_allowed(self, adapter):
        ok, reason = adapter.check_file_type("report.pdf")
        assert ok is True

    def test_pdf_uppercase(self, adapter):
        ok, reason = adapter.check_file_type("report.PDF")
        assert ok is True

    def test_word_rejected(self, adapter):
        ok, reason = adapter.check_file_type("report.docx")
        assert ok is False
        assert "不支持" in reason

    def test_empty_filename(self, adapter):
        ok, reason = adapter.check_file_type("")
        assert ok is False


class TestInstructionParsing:
    """指令解析集成测试。"""

    def test_parse_convert(self, adapter):
        result = adapter.parse_instruction("/convert 敏感模式")
        assert result.action == "convert"
        assert result.options.get("sensitive_mode") is True


class TestSendResult:
    """结果回传测试。"""

    @pytest.mark.asyncio
    async def test_send_text_result(self, adapter):
        with patch.object(adapter.client, "send_text", new_callable=AsyncMock) as mock:
            mock.return_value = {}
            await adapter.send_result("oc_test_chat", "转换完成")
            mock.assert_called_once_with("oc_test_chat", "转换完成")

    @pytest.mark.asyncio
    async def test_send_file_result(self, adapter):
        with patch.object(adapter.client, "send_file", new_callable=AsyncMock) as mock:
            mock.return_value = {}
            await adapter.send_result("oc_test_chat", "", "/path/to/result.md")
            mock.assert_called_once_with("oc_test_chat", "/path/to/result.md")


class TestSendFailure:
    """失败通知测试。"""

    @pytest.mark.asyncio
    async def test_send_failure_message(self, adapter):
        with patch.object(adapter.client, "send_text", new_callable=AsyncMock) as mock:
            mock.return_value = {}
            await adapter.send_failure("oc_test_chat", "job_20260101_abc12345", "超时")
            mock.assert_called_once()
            call_args = mock.call_args
            assert "abc12345" in call_args[0][1]
            assert "超时" in call_args[0][1]
