"""测试 Job 完整生命周期：create -> claim -> run -> complete/fail。"""

import os
import tempfile
import shutil
import pytest

from docconv.service.job_models import (
    JobStatus, JobRecord, ConversionRequest,
    ServiceError, ErrorCodes,
)
from docconv.service.job_store import SQLiteJobStore
from docconv.service.workspace import JobWorkspace
from docconv.service.conversion_job_service import ConversionJobService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_data_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def service(tmp_data_dir):
    db_path = os.path.join(tmp_data_dir, "job_store.sqlite3")
    store = SQLiteJobStore(db_path=db_path)
    config = {
        "storage_root": tmp_data_dir,
        "max_queued_jobs": 5,
        "max_running_jobs": 1,
        "retention_hours": 24,
    }
    return ConversionJobService(config=config, store=store)


def _create_pdf(tmp_dir: str, name: str = "test.pdf") -> str:
    """创建一个伪 PDF 文件。"""
    path = os.path.join(tmp_dir, name)
    with open(path, "wb") as f:
        f.write(b"%PDF-1.4 fake content")
    return path


# ---------------------------------------------------------------------------
# Full lifecycle: create -> claim -> complete
# ---------------------------------------------------------------------------

class TestFullLifecycle:
    def test_happy_path(self, service, tmp_data_dir):
        """完整生命周期：创建 -> claim -> 完成。"""
        # 1) 创建
        pdf_path = _create_pdf(tmp_data_dir)
        req = ConversionRequest(
            source="cli",
            input_file_path=pdf_path,
            original_filename="test.pdf",
        )
        result = service.create_job(req)
        job_id = result["job_id"]
        assert result["status"] == JobStatus.QUEUED

        # 2) claim
        store = service.store
        job = store.claim_next_job("w1")
        assert job is not None
        assert job.job_id == job_id
        assert job.status == JobStatus.RUNNING
        assert job.locked_by == "w1"

        # 3) 完成
        done = service.complete_job(job_id)
        assert done["status"] == JobStatus.SUCCEEDED

        # 4) 验证最终状态
        final = service.get_job(job_id)
        assert final.status == JobStatus.SUCCEEDED

    def test_fail_path(self, service, tmp_data_dir):
        """创建 -> claim -> 失败。"""
        pdf_path = _create_pdf(tmp_data_dir)
        req = ConversionRequest(
            source="cli",
            input_file_path=pdf_path,
            original_filename="fail.pdf",
        )
        result = service.create_job(req)
        job_id = result["job_id"]

        store = service.store
        store.claim_next_job("w1")

        done = service.fail_job(
            job_id,
            error_type="ConversionError",
            error_message="Failed to parse page 3",
        )
        assert done["status"] == JobStatus.FAILED

        final = service.get_job(job_id)
        assert final.status == JobStatus.FAILED
        assert final.error_type == "ConversionError"

    def test_cancel_queued_job(self, service, tmp_data_dir):
        """创建后直接取消（queued 状态）。"""
        pdf_path = _create_pdf(tmp_data_dir)
        req = ConversionRequest(
            source="web",
            input_file_path=pdf_path,
            original_filename="cancel.pdf",
        )
        result = service.create_job(req)
        job_id = result["job_id"]

        cancelled = service.cancel_job(job_id)
        assert cancelled["status"] == JobStatus.CANCELLED

        final = service.get_job(job_id)
        assert final.status == JobStatus.CANCELLED

    def test_cancel_running_job(self, service, tmp_data_dir):
        """running 状态的任务也可以取消。"""
        pdf_path = _create_pdf(tmp_data_dir)
        req = ConversionRequest(
            source="cli",
            input_file_path=pdf_path,
            original_filename="running_cancel.pdf",
        )
        result = service.create_job(req)
        job_id = result["job_id"]

        # claim 使其变为 running
        service.store.claim_next_job("w1")

        cancelled = service.cancel_job(job_id)
        assert cancelled["status"] == JobStatus.CANCELLED


# ---------------------------------------------------------------------------
# Queue overflow (SVC2003)
# ---------------------------------------------------------------------------

class TestQueueOverflow:
    def test_reject_when_queue_full(self, service, tmp_data_dir):
        """队列满时拒绝新任务。"""
        for i in range(5):  # max_queued_jobs=5
            pdf_path = _create_pdf(tmp_data_dir, f"fill{i}.pdf")
            req = ConversionRequest(
                source="cli",
                input_file_path=pdf_path,
                original_filename=f"fill{i}.pdf",
            )
            service.create_job(req)

        # 第 6 个应该被拒绝
        pdf_path = _create_pdf(tmp_data_dir, "overflow.pdf")
        req = ConversionRequest(
            source="cli",
            input_file_path=pdf_path,
            original_filename="overflow.pdf",
        )
        with pytest.raises(ServiceError) as exc:
            service.create_job(req)
        assert exc.value.code == ErrorCodes.SVC2003


# ---------------------------------------------------------------------------
# Invalid state transitions
# ---------------------------------------------------------------------------

class TestInvalidStateTransitions:
    def test_cancel_succeeded_job(self, service, tmp_data_dir):
        """取消已成功的任务应抛 SVC2002。"""
        pdf_path = _create_pdf(tmp_data_dir)
        req = ConversionRequest(
            source="cli",
            input_file_path=pdf_path,
            original_filename="s.pdf",
        )
        result = service.create_job(req)
        job_id = result["job_id"]

        # claim -> complete
        service.store.claim_next_job("w1")
        service.complete_job(job_id)

        # 尝试取消已完成的任务
        with pytest.raises(ServiceError) as exc:
            service.cancel_job(job_id)
        assert exc.value.code == ErrorCodes.SVC2002

    def test_fail_already_failed_job(self, service, tmp_data_dir):
        """failed 任务不能再 fail。"""
        pdf_path = _create_pdf(tmp_data_dir)
        req = ConversionRequest(
            source="cli",
            input_file_path=pdf_path,
            original_filename="ff.pdf",
        )
        result = service.create_job(req)
        job_id = result["job_id"]

        service.store.claim_next_job("w1")
        service.fail_job(job_id, "err", "msg")

        # 再次失败
        with pytest.raises(ServiceError) as exc:
            service.fail_job(job_id, "err2", "msg2")
        assert exc.value.code == ErrorCodes.SVC2002


# ---------------------------------------------------------------------------
# Workspace path traversal protection
# ---------------------------------------------------------------------------

class TestWorkspacePathProtection:
    def test_path_traversal_in_job_id(self, tmp_data_dir):
        """job_id 包含 .. 时应拒绝。"""
        with pytest.raises(ValueError, match="job_id"):
            JobWorkspace(
                job_id="job_../../etc/passwd",
                storage_root=tmp_data_dir,
            )

    def test_resolve_rejects_traversal(self, tmp_data_dir):
        """resolve 应拒绝路径穿越。"""
        ws = JobWorkspace(job_id="job_safe", storage_root=tmp_data_dir)
        # 尝试用 ../ 穿越
        with pytest.raises(ValueError, match="路径穿越"):
            ws.resolve("input", "../../../etc/passwd")

    def test_resolve_rejects_invalid_subdir(self, tmp_data_dir):
        """resolve 应拒绝非法子目录。"""
        ws = JobWorkspace(job_id="job_safe2", storage_root=tmp_data_dir)
        with pytest.raises(ValueError, match="非法的子目录"):
            ws.resolve("secrets", "key.pem")


# ---------------------------------------------------------------------------
# Progress update
# ---------------------------------------------------------------------------

class TestProgressUpdate:
    def test_update_progress(self, service, tmp_data_dir):
        """进度更新应正确写入。"""
        pdf_path = _create_pdf(tmp_data_dir)
        req = ConversionRequest(
            source="cli",
            input_file_path=pdf_path,
            original_filename="prog.pdf",
        )
        result = service.create_job(req)
        job_id = result["job_id"]

        service.update_progress(job_id, {
            "total_pages": 10,
            "completed_pages": 3,
            "failed_pages": 0,
        })

        job = service.get_job(job_id)
        assert job.progress_json["total_pages"] == 10
        assert job.progress_json["completed_pages"] == 3


# ---------------------------------------------------------------------------
# Error message sanitization
# ---------------------------------------------------------------------------

class TestErrorSanitization:
    def test_api_key_redacted(self, service, tmp_data_dir):
        """错误消息中的 API Key 应被脱敏。"""
        pdf_path = _create_pdf(tmp_data_dir)
        req = ConversionRequest(
            source="cli",
            input_file_path=pdf_path,
            original_filename="err.pdf",
        )
        result = service.create_job(req)
        job_id = result["job_id"]
        service.store.claim_next_job("w1")

        service.fail_job(
            job_id,
            "APIError",
            "Failed with key sk-abc1234567890abcdef1234567890",
        )

        job = service.get_job(job_id)
        assert "sk-abc1234567890abcdef1234567890" not in job.error_message
        assert "***REDACTED***" in job.error_message

    def test_error_message_truncated(self, service, tmp_data_dir):
        """错误消息超过 2000 字符应被截断。"""
        long_msg = "x" * 3000
        pdf_path = _create_pdf(tmp_data_dir)
        req = ConversionRequest(
            source="cli",
            input_file_path=pdf_path,
            original_filename="long.pdf",
        )
        result = service.create_job(req)
        job_id = result["job_id"]
        service.store.claim_next_job("w1")

        service.fail_job(job_id, "LongError", long_msg)
        job = service.get_job(job_id)
        assert len(job.error_message) <= 2003  # 2000 + "..."
