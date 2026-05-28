"""BI-10: 任务关联存储（bot_correlations）测试。"""

import pytest

from docconv.infra.bot_correlation_store import BotCorrelationStore
from docconv.integrations.common import BotJobCorrelation


@pytest.fixture()
def store():
    """使用内存数据库。"""
    s = BotCorrelationStore()
    yield s
    s.close()


class TestCreateCorrelation:
    """创建关联记录测试。"""

    def test_create_with_auto_id(self, store):
        corr = BotJobCorrelation(
            job_id="job_001",
            platform="telegram",
            external_message_id="msg_001",
            chat_id="chat_123",
            sender_id="user_456",
        )
        result = store.create_correlation(corr)
        assert result.id != ""
        assert result.created_at != ""
        assert result.updated_at != ""

    def test_create_with_explicit_id(self, store):
        corr = BotJobCorrelation(
            id="corr_explicit",
            job_id="job_002",
            platform="feishu",
            external_message_id="msg_002",
            chat_id="chat_789",
            sender_id="user_012",
        )
        result = store.create_correlation(corr)
        assert result.id == "corr_explicit"


class TestGetByJobId:
    """根据 job_id 查询测试。"""

    def test_get_existing(self, store):
        corr = BotJobCorrelation(
            job_id="job_100",
            platform="telegram",
            external_message_id="msg_100",
            chat_id="chat_100",
            sender_id="user_100",
        )
        store.create_correlation(corr)

        results = store.get_by_job_id("job_100")
        assert len(results) == 1
        assert results[0].platform == "telegram"
        assert results[0].chat_id == "chat_100"

    def test_get_nonexistent(self, store):
        results = store.get_by_job_id("nonexistent")
        assert len(results) == 0

    def test_multiple_correlations_same_job(self, store):
        """一个 job 可能对应多个平台消息。"""
        store.create_correlation(BotJobCorrelation(
            job_id="job_200", platform="telegram",
            external_message_id="msg_a", chat_id="chat_a", sender_id="u1",
        ))
        store.create_correlation(BotJobCorrelation(
            job_id="job_200", platform="telegram",
            external_message_id="msg_b", chat_id="chat_a", sender_id="u1",
        ))

        results = store.get_by_job_id("job_200")
        assert len(results) == 2


class TestGetByChatId:
    """根据 chat_id 查询测试。"""

    def test_get_existing(self, store):
        store.create_correlation(BotJobCorrelation(
            job_id="job_300", platform="feishu",
            external_message_id="msg_300", chat_id="chat_300", sender_id="u3",
        ))

        results = store.get_by_chat_id("chat_300")
        assert len(results) == 1
        assert results[0].job_id == "job_300"

    def test_get_nonexistent(self, store):
        results = store.get_by_chat_id("nonexistent")
        assert len(results) == 0


class TestGetByPlatformAndExternalId:
    """根据平台和外部消息 ID 查询测试。"""

    def test_get_existing(self, store):
        store.create_correlation(BotJobCorrelation(
            job_id="job_400", platform="telegram",
            external_message_id="msg_400", chat_id="chat_400", sender_id="u4",
        ))

        result = store.get_by_platform_and_external_id("telegram", "msg_400")
        assert result is not None
        assert result.job_id == "job_400"

    def test_get_nonexistent(self, store):
        result = store.get_by_platform_and_external_id("telegram", "nonexistent")
        assert result is None


class TestUpdateJobId:
    """更新 job_id 测试。"""

    def test_update(self, store):
        corr = store.create_correlation(BotJobCorrelation(
            job_id="old_job_id", platform="telegram",
            external_message_id="msg_500", chat_id="chat_500", sender_id="u5",
        ))

        store.update_job_id(corr.id, "new_job_id")
        results = store.get_by_job_id("new_job_id")
        assert len(results) == 1
        assert results[0].id == corr.id

        # 旧 job_id 不应再有结果
        old_results = store.get_by_job_id("old_job_id")
        assert len(old_results) == 0


class TestDelete:
    """删除关联记录测试。"""

    def test_delete_existing(self, store):
        corr = store.create_correlation(BotJobCorrelation(
            job_id="job_600", platform="feishu",
            external_message_id="msg_600", chat_id="chat_600", sender_id="u6",
        ))

        assert store.delete(corr.id) is True
        results = store.get_by_job_id("job_600")
        assert len(results) == 0

    def test_delete_nonexistent(self, store):
        assert store.delete("nonexistent_id") is False
