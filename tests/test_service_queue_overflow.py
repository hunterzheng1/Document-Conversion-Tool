"""测试队列溢出保护（max_queued_jobs）。"""

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
        "max_queued_jobs": 3,
        "max_running_jobs": 1,
        "retention_hours": 24,
    }
    return ConversionJobService(config=config, store=store)


def _make_request(tmp_dir: str, filename: str = "test.pdf") -> ConversionRequest:
    """创建一个有效的转换请求。"""
    f_path = os.path.join(tmp_dir, filename)
    with open(f_path, "wb") as f:
        f.write(b"%PDF-1.4 fake pdf content")
    return ConversionRequest(
        source="cli",
        input_file_path=f_path,
        original_filename=filename,
    )


class TestQueueOverflow:
    def test_create_job_within_limit(self, service, tmp_data_dir):
        """队列未满时创建成功。"""
        req = _make_request(tmp_data_dir, "test1.pdf")
        result = service.create_job(req)
        assert result["status"] == "queued"
        assert result["job_id"].startswith("job_")

    def test_create_job_at_limit(self, service, tmp_data_dir):
        """队列刚好满时（3/3），拒绝新任务。"""
        # 创建 3 个任务（max_queued_jobs=3）
        for i in range(3):
            req = _make_request(tmp_data_dir, f"test{i}.pdf")
            service.create_job(req)

        # 第 4 个应该被拒绝
        req = _make_request(tmp_data_dir, "overflow.pdf")
        with pytest.raises(ServiceError) as exc:
            service.create_job(req)
        assert exc.value.code == ErrorCodes.SVC2003
        assert "队列已满" in exc.value.message

    def test_create_job_after_claim_has_room(self, service, tmp_data_dir):
        """claim 一个任务后，queued 数量减少，可以创建新任务。"""
        # 创建 3 个任务
        for i in range(3):
            req = _make_request(tmp_data_dir, f"test{i}.pdf")
            service.create_job(req)

        # claim 一个
        store = service.store
        job = store.claim_next_job("w1")
        assert job is not None
        assert job.status == JobStatus.RUNNING

        # 现在 queued=2，可以再创建一个
        req = _make_request(tmp_data_dir, "after_claim.pdf")
        result = service.create_job(req)
        assert result["status"] == "queued"

    def test_error_code_is_svc2003(self, service, tmp_data_dir):
        """确认错误码为 SVC2003（非 SVC1002）。"""
        for i in range(3):
            req = _make_request(tmp_data_dir, f"fill{i}.pdf")
            service.create_job(req)

        req = _make_request(tmp_data_dir, "overflow.pdf")
        with pytest.raises(ServiceError) as exc:
            service.create_job(req)
        # 必须是 SVC2003，不是 SVC1002
        assert exc.value.code == ErrorCodes.SVC2003
