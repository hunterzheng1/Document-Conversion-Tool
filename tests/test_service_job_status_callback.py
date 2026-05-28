"""BI-11: 终态结果回传（JobStatusCallback）测试。"""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from docconv.service.job_status_callback import JobStatusCallback
from docconv.integrations.common import BotJobCorrelation
from docconv.service.job_models import JobRecord, JobStatus


def _make_job(status: str = "succeeded") -> JobRecord:
    return JobRecord(
        job_id="job_20260101_abc123",
        source="telegram",
        status=status,
        original_filename="test.pdf",
        input_path="/tmp/test/input.pdf",
        output_path="/tmp/test/output/result.md",
        report_path="/tmp/test/output/report.md",
        instruction="/convert",
        error_type="timeout" if status == "failed" else "",
        error_message="Connection timed out after 30s" if status == "failed" else "",
    )


@pytest.fixture()
def callback():
    """创建回调处理器（使用 mock 依赖）。"""
    mock_store = MagicMock()
    mock_job_service = MagicMock()

    mock_telegram_adapter = MagicMock()
    mock_telegram_adapter.send_result = AsyncMock()
    mock_telegram_adapter.send_failure = AsyncMock()

    callback = JobStatusCallback(
        correlation_store=mock_store,
        job_service=mock_job_service,
        telegram_adapter=mock_telegram_adapter,
        feishu_adapter=None,
        send_report=True,
    )
    callback._mock_store = mock_store
    callback._mock_job_service = mock_job_service
    callback._mock_telegram_adapter = mock_telegram_adapter
    return callback


class TestHandleTerminalState:
    """处理终态测试。"""

    @pytest.mark.asyncio
    async def test_no_correlations_skipped(self, callback):
        """无关联记录时应跳过回传。"""
        callback._mock_store.get_by_job_id.return_value = []
        callback._mock_job_service.get_job.return_value = _make_job()

        await callback.handle_terminal_state("job_001")
        callback._mock_telegram_adapter.send_result.assert_not_called()

    @pytest.mark.asyncio
    async def test_job_not_found(self, callback):
        """job 不存在时应记录错误并返回。"""
        callback._mock_job_service.get_job.side_effect = Exception("not found")

        await callback.handle_terminal_state("job_999")  # 不应抛异常

    @pytest.mark.asyncio
    async def test_unknown_platform_skipped(self, callback):
        """未知平台应跳过。"""
        corr = BotJobCorrelation(
            job_id="job_001",
            platform="unknown_platform",
            external_message_id="msg_1",
            chat_id="chat_1",
            sender_id="user_1",
        )
        callback._mock_store.get_by_job_id.return_value = [corr]
        callback._mock_job_service.get_job.return_value = _make_job()

        await callback.handle_terminal_state("job_001")
        callback._mock_telegram_adapter.send_result.assert_not_called()


class TestSendSuccess:
    """成功回传测试。"""

    @pytest.mark.asyncio
    async def test_send_success_with_output_file(self, callback):
        """成功 job 应发送结果到平台。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "result.md"
            output_path.write_text("# Test Result\n\nConverted content.")

            corr = BotJobCorrelation(
                job_id="job_001",
                platform="telegram",
                external_message_id="msg_1",
                chat_id="chat_1",
                sender_id="user_1",
            )
            job = _make_job(status="succeeded")
            job.output_path = str(output_path)

            callback._mock_store.get_by_job_id.return_value = [corr]
            callback._mock_job_service.get_job.return_value = job

            await callback.handle_terminal_state("job_001")
            callback._mock_telegram_adapter.send_result.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_report_enabled(self, callback):
        """send_report=True 时应尝试发送报告文件。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "result.md"
            output_path.write_text("# Result")

            corr = BotJobCorrelation(
                job_id="job_002",
                platform="telegram",
                external_message_id="msg_2",
                chat_id="chat_2",
                sender_id="user_2",
            )
            job = _make_job(status="succeeded")
            job.output_path = str(output_path)

            callback.send_report = True
            callback._mock_store.get_by_job_id.return_value = [corr]
            callback._mock_job_service.get_job.return_value = job

            await callback.handle_terminal_state("job_002")
            # 应该调用了 send_result
            assert callback._mock_telegram_adapter.send_result.called


class TestSendFailure:
    """失败回传测试。"""

    @pytest.mark.asyncio
    async def test_send_failure_sends_sanitized_summary(self, callback):
        """失败 job 应发送脱敏失败摘要。"""
        corr = BotJobCorrelation(
            job_id="job_003",
            platform="telegram",
            external_message_id="msg_3",
            chat_id="chat_3",
            sender_id="user_3",
        )
        job = _make_job(status="failed")

        callback._mock_store.get_by_job_id.return_value = [corr]
        callback._mock_job_service.get_job.return_value = job

        await callback.handle_terminal_state("job_003")
        callback._mock_telegram_adapter.send_failure.assert_called_once()
        call_args = callback._mock_telegram_adapter.send_failure.call_args
        assert "chat_3" == call_args[0][0]
        assert "Connection timed out" in call_args[0][2]


class TestCallbackErrorDoesNotAffectJob:
    """回传失败不影响 job 终态。"""

    @pytest.mark.asyncio
    async def test_callback_error_logged(self, callback):
        """回传发送失败应记录日志但不抛异常。"""
        corr = BotJobCorrelation(
            job_id="job_004",
            platform="telegram",
            external_message_id="msg_4",
            chat_id="chat_4",
            sender_id="user_4",
        )
        job = _make_job(status="succeeded")

        callback._mock_store.get_by_job_id.return_value = [corr]
        callback._mock_job_service.get_job.return_value = job
        callback._mock_telegram_adapter.send_result = AsyncMock(
            side_effect=RuntimeError("send failed")
        )

        # 不应抛异常
        await callback.handle_terminal_state("job_004")
