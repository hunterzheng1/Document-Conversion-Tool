"""BI-01: 基础类型与 BotAdapter 协议测试。"""

import pytest

from docconv.integrations.common import (
    BotMessage,
    BotJobCorrelation,
    BotAdapter,
    BotPlatform,
)


class TestBotPlatform:
    """BotPlatform 枚举测试。"""

    def test_telegram_value(self):
        assert BotPlatform.TELEGRAM == "telegram"

    def test_feishu_value(self):
        assert BotPlatform.FEISHU == "feishu"

    def test_from_string(self):
        assert BotPlatform("telegram") == BotPlatform.TELEGRAM
        assert BotPlatform("feishu") == BotPlatform.FEISHU

    def test_all_platforms(self):
        members = list(BotPlatform)
        assert len(members) == 2


class TestBotMessage:
    """BotMessage dataclass 测试。"""

    def test_required_fields(self):
        """BotMessage 包含 spec 中定义的全部 8 个字段。"""
        msg = BotMessage(
            platform="telegram",
            external_message_id="msg_001",
            chat_id="chat_123",
            sender_id="user_456",
            file_id="file_789",
            filename="test.pdf",
            instruction="/convert",
        )
        assert msg.platform == "telegram"
        assert msg.external_message_id == "msg_001"
        assert msg.chat_id == "chat_123"
        assert msg.sender_id == "user_456"
        assert msg.file_id == "file_789"
        assert msg.filename == "test.pdf"
        assert msg.instruction == "/convert"
        # job_id 默认为空字符串
        assert msg.job_id == ""

    def test_job_id_optional(self):
        msg = BotMessage(
            platform="feishu",
            external_message_id="msg_002",
            chat_id="chat_789",
            sender_id="user_012",
            file_id="file_345",
            filename="report.pdf",
            instruction="/convert 敏感模式",
            job_id="job_20260101_abc123",
        )
        assert msg.job_id == "job_20260101_abc123"

    def test_platform_meta_default(self):
        msg = BotMessage(
            platform="telegram",
            external_message_id="msg_003",
            chat_id="chat_1",
            sender_id="user_1",
            file_id="file_1",
            filename="a.pdf",
            instruction="",
        )
        assert msg.platform_meta == {}

    def test_platform_meta_custom(self):
        msg = BotMessage(
            platform="telegram",
            external_message_id="msg_004",
            chat_id="chat_2",
            sender_id="user_2",
            file_id="file_2",
            filename="b.pdf",
            instruction="",
            platform_meta={"update_id": 12345},
        )
        assert msg.platform_meta["update_id"] == 12345


class TestBotJobCorrelation:
    """BotJobCorrelation dataclass 测试。"""

    def test_default_values(self):
        corr = BotJobCorrelation()
        assert corr.id == ""
        assert corr.job_id == ""
        assert corr.platform == ""
        assert corr.external_message_id == ""
        assert corr.chat_id == ""
        assert corr.sender_id == ""
        assert corr.created_at == ""
        assert corr.updated_at == ""

    def test_full_creation(self):
        corr = BotJobCorrelation(
            id="corr_001",
            job_id="job_20260101_xyz",
            platform="telegram",
            external_message_id="msg_100",
            chat_id="chat_abc",
            sender_id="user_def",
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:01Z",
        )
        assert corr.job_id == "job_20260101_xyz"
        assert corr.platform == "telegram"


class TestBotAdapter:
    """BotAdapter 抽象基类测试。"""

    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            BotAdapter()

    def test_abstract_methods_defined(self):
        """验证所有必需抽象方法已定义。"""
        abstract_methods = BotAdapter.__abstractmethods__
        assert "verify_source" in abstract_methods
        assert "parse_message" in abstract_methods
        assert "download_file" in abstract_methods
        assert "send_result" in abstract_methods
        assert "send_failure" in abstract_methods
        assert "send_text" in abstract_methods

    def test_concrete_implementation(self):
        """验证具体子类可以实例化并调用方法。"""

        class DummyAdapter(BotAdapter):
            def verify_source(self, payload):
                return True

            def parse_message(self, payload):
                return BotMessage(
                    platform="test",
                    external_message_id="1",
                    chat_id="c",
                    sender_id="s",
                    file_id="f",
                    filename="t.pdf",
                    instruction="",
                )

            async def download_file(self, file_id, dest_path):
                return dest_path

            async def send_result(self, chat_id, result_text, file_path=""):
                pass

            async def send_failure(self, chat_id, job_id, error_summary):
                pass

            async def send_text(self, chat_id, text):
                pass

        adapter = DummyAdapter()
        assert adapter.verify_source({}) is True
