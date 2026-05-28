"""测试 SQLiteJobStore 和 JobWorkspace。"""

import os
import tempfile
import shutil
import pytest

from docconv.service.job_models import JobStatus, JobRecord
from docconv.service.job_store import SQLiteJobStore
from docconv.service.workspace import JobWorkspace


@pytest.fixture()
def tmp_data_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def store(tmp_data_dir):
    db_path = os.path.join(tmp_data_dir, "job_store.sqlite3")
    return SQLiteJobStore(db_path=db_path)


class TestSQLiteJobStore:
    def test_init_creates_db(self, tmp_data_dir):
        db_path = os.path.join(tmp_data_dir, "job_store.sqlite3")
        store = SQLiteJobStore(db_path=db_path)
        assert os.path.exists(db_path)

    def test_insert_and_get_job(self, store):
        record = JobRecord(
            job_id="job_test_001",
            source="cli",
            original_filename="test.pdf",
            input_path="/tmp/input.pdf",
        )
        store.insert(record)
        retrieved = store.get("job_test_001")
        assert retrieved is not None
        assert retrieved.job_id == "job_test_001"
        assert retrieved.source == "cli"

    def test_get_missing_job_returns_none(self, store):
        assert store.get("nonexistent") is None

    def test_update_job(self, store):
        record = JobRecord(
            job_id="job_test_002",
            source="web",
            original_filename="doc.pdf",
            input_path="/tmp/doc.pdf",
        )
        store.insert(record)
        store.update("job_test_002", {"status": JobStatus.RUNNING, "locked_by": "w1"})
        j = store.get("job_test_002")
        assert j.status == JobStatus.RUNNING
        assert j.locked_by == "w1"

    def test_atomic_claim(self, store):
        store.insert(JobRecord(
            job_id="job_q1", source="web", original_filename="a.pdf", input_path="/x",
        ))
        result = store.claim_next_job(worker_id="w1")
        assert result is not None
        assert result.job_id == "job_q1"
        assert result.status == JobStatus.RUNNING
        assert result.locked_by == "w1"

    def test_atomic_claim_empty_queue(self, store):
        result = store.claim_next_job(worker_id="w1")
        assert result is None

    def test_list_by_status(self, store):
        for i in range(5):
            store.insert(JobRecord(
                job_id=f"job_{i}", source="cli", original_filename=f"t{i}.pdf",
                input_path=f"/t{i}",
            ))
        jobs = store.list_by_status(JobStatus.QUEUED)
        assert len(jobs) == 5

    def test_complete_and_fail_job(self, store):
        store.insert(JobRecord(
            job_id="job_r1", source="cli", original_filename="x.pdf", input_path="/x",
        ))
        store.claim_next_job(worker_id="w1")
        store.update("job_r1", {"status": JobStatus.SUCCEEDED, "output_path": "/out", "report_path": "/report"})
        j = store.get("job_r1")
        assert j.status == JobStatus.SUCCEEDED
        assert j.output_path == "/out"

        store.insert(JobRecord(
            job_id="job_f1", source="cli", original_filename="y.pdf", input_path="/y",
        ))
        store.claim_next_job(worker_id="w1")
        store.update("job_f1", {"status": JobStatus.FAILED, "error_type": "conversion_error", "error_message": "failed"})
        j = store.get("job_f1")
        assert j.status == JobStatus.FAILED
        assert j.error_type == "conversion_error"


class TestJobWorkspace:
    def test_workspace_root(self, tmp_data_dir):
        ws = JobWorkspace(job_id="job_ws_test", storage_root=tmp_data_dir)
        expected = os.path.join(tmp_data_dir, "jobs", "job_ws_test")
        assert str(ws.workspace_root) == expected

    def test_resolve_creates_dirs(self, tmp_data_dir):
        ws = JobWorkspace(job_id="job_ws_test", storage_root=tmp_data_dir)
        ws.resolve("input", "test.pdf")  # triggers directory creation
        assert os.path.isdir(os.path.join(tmp_data_dir, "jobs", "job_ws_test", "input"))
        assert os.path.isdir(os.path.join(tmp_data_dir, "jobs", "job_ws_test", "output"))
        assert os.path.isdir(os.path.join(tmp_data_dir, "jobs", "job_ws_test", "state"))
        assert os.path.isdir(os.path.join(tmp_data_dir, "jobs", "job_ws_test", "tmp"))

    def test_workspace_paths(self, tmp_data_dir):
        ws = JobWorkspace(job_id="job_paths", storage_root=tmp_data_dir)
        input_path = ws.resolve("input", "doc.pdf")
        assert "doc.pdf" in str(input_path)
        assert "job_paths" in str(input_path)

    def test_cleanup_workspace(self, tmp_data_dir):
        ws = JobWorkspace(job_id="job_cleanup", storage_root=tmp_data_dir)
        ws.resolve("input", "x.pdf")  # trigger creation
        root = ws.workspace_root
        assert os.path.isdir(root)
        ws.cleanup()
        assert not os.path.exists(root)
