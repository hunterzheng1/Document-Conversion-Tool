"""BI-13: 错误处理与日志脱敏测试。"""

import logging
from unittest.mock import patch

from docconv.infra.bot_error_codes import (
    BotErrorCodes,
    BotErrorResponse,
    AuditEvent,
    AuditTimer,
    hash_chat_id,
    log_audit,
)
from docconv.infra.bot_config import redact_secrets


class TestBotErrorCodes:
    """错误码常量测试。"""

    def test_auth_unauthorized(self):
        assert BotErrorCodes.AUTH_UNAUTHORIZED == "3001"

    def test_auth_webhook_failed(self):
        assert BotErrorCodes.AUTH_WEBHOOK_FAILED == "3002"

    def test_file_unsupported(self):
        assert BotErrorCodes.FILE_UNSUPPORTED == "1001"

    def test_instruction_unsupported(self):
        assert BotErrorCodes.INSTRUCTION_UNSUPPORTED == "1004"

    def test_download_failed(self):
        assert BotErrorCodes.DOWNLOAD_FAILED == "4001"

    def test_send_failed(self):
        assert BotErrorCodes.SEND_FAILED == "4002"


class TestBotErrorResponse:
    """错误响应测试。"""

    def test_to_dict(self):
        resp = BotErrorResponse(
            error_code="3001",
            message="Unauthorized source",
        )
        d = resp.to_dict()
        assert d["error"]["code"] == "3001"
        assert d["error"]["message"] == "Unauthorized source"

    def test_message_redacted(self):
        """错误消息中包含 token 时应脱敏。"""
        resp = BotErrorResponse(
            error_code="4001",
            message="Download failed: token=abc123secret456",
        )
        d = resp.to_dict()
        assert "abc123secret456" not in d["error"]["message"]
        assert "***" in d["error"]["message"]

    def test_details_not_redacted_unless_string(self):
        """details 中非字符串字段不应被脱敏。"""
        resp = BotErrorResponse(
            error_code="1001",
            message="Unsupported file",
            details={"attempted": 3, "file_type": "exe"},
        )
        d = resp.to_dict()
        assert d["error"]["details"]["attempted"] == 3


class TestHashChatId:
    """chat_id 哈希测试。"""

    def test_deterministic(self):
        assert hash_chat_id("chat_123") == hash_chat_id("chat_123")

    def test_different_inputs(self):
        assert hash_chat_id("chat_123") != hash_chat_id("chat_456")

    def test_length(self):
        assert len(hash_chat_id("chat_123")) == 8


class TestAuditEvent:
    """审计日志事件测试。"""

    def test_log_audit_no_error(self, caplog):
        event = AuditEvent(
            platform="telegram",
            chat_hash="abcd1234",
            job_id="job_001",
            event_type="job_created",
            duration_ms=150.5,
        )
        with caplog.at_level(logging.INFO):
            log_audit(event)
        assert any("job_created" in record.message for record in caplog.records)

    def test_log_audit_with_error(self, caplog):
        event = AuditEvent(
            platform="feishu",
            chat_hash="efgh5678",
            job_id="job_002",
            event_type="failed",
            duration_ms=5000.0,
            error_type="timeout",
            error_code="4002",
        )
        with caplog.at_level(logging.WARNING):
            log_audit(event)
        assert any("4002" in record.message for record in caplog.records)

    def test_extra_redacted(self, caplog):
        """extra 中的字符串应被脱敏。"""
        event = AuditEvent(
            platform="telegram",
            chat_hash="abcd1234",
            job_id="job_003",
            event_type="downloaded",
            duration_ms=2000.0,
            extra={"file_url": "https://api.telegram.org/file/bot1234567890:ABCdefghijklmnopqrst/path"},
        )
        with caplog.at_level(logging.INFO):
            log_audit(event)
        # 验证日志记录中不包含完整 token（bot+数字+长字符串模式应被脱敏）
        for record in caplog.records:
            assert "ABCdefghijklmnopqrst" not in record.message


class TestAuditTimer:
    """审计计时器测试。"""

    def test_records_duration(self):
        event = AuditEvent()
        with AuditTimer(event):
            pass  # 极短时间
        assert event.duration_ms >= 0

    def test_measures_elapsed(self):
        import time
        event = AuditEvent()
        with AuditTimer(event):
            time.sleep(0.05)
        assert event.duration_ms >= 40  # 至少 40ms


class TestRedactSecrets:
    """复用 redact_secrets 测试（已在 BI-03 中测试）。"""

    def test_redact_bearer_token(self):
        text = "Authorization: Bearer eyJhbGciOiJSUzI1NiJ9"
        result = redact_secrets(text)
        assert "eyJhbGci" not in result
