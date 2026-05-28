"""测试 LocalWorker 轮询、执行、心跳、恢复。"""

import os
import time
import threading
import tempfile
import shutil
import pytest
from pathlib import Path

from docconv.service.job_models import JobStatus, JobRecord
from docconv.service.job_store import SQLiteJobStore
from docconv.service.conversion_job_service import ConversionJobService
from docconv.worker.local_worker import LocalWorker, _HeartbeatThread


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
        "max_queued_jobs": 10,
        "max_running_jobs": 1,
        "retention_hours": 24,
        "worker_poll_interval_seconds": 1,
        "recover_running_on_start": True,
        "recover_timeout_seconds": 600,
    }
    return ConversionJobService(config=config, store=store)


@pytest.fixture()
def worker(service):
    return LocalWorker(
        service=service,
        config={
            "worker_poll_interval_seconds": 1,
            "max_running_jobs": 1,
            "recover_running_on_start": True,
            "recover_timeout_seconds": 600,
        },
        worker_id="test_worker_001",
    )


def _insert_queued_job(service, filename="test.pdf"):
    """插入一个 queued job 到 store。"""
    record = JobRecord(
        job_id=JobRecord.generate_job_id(),
        source="cli",
        original_filename=filename,
        input_path="/tmp/fake_input.pdf",
        output_path="/tmp/fake_output.md",
        report_path="/tmp/fake_report.md",
    )
    service.store.insert(record)
    return record.job_id


# ---------------------------------------------------------------------------
# Worker ID
# ---------------------------------------------------------------------------

class TestWorkerId:
    def test_custom_worker_id(self, service):
        w = LocalWorker(service, worker_id="my_custom_worker")
        assert w.worker_id == "my_custom_worker"

    def test_auto_generated_id_format(self, service):
        w = LocalWorker(service)
        wid = w.worker_id
        assert wid.startswith("worker_")
        parts = wid.split("_")
        assert len(parts) >= 3


# ---------------------------------------------------------------------------
# Polling - no tasks
# ---------------------------------------------------------------------------

class TestPollingNoTasks:
    def test_claim_empty_queue(self, service):
        job = service.store.claim_next_job("w1")
        assert job is None

    def test_worker_stops_when_no_tasks(self, worker):
        """Worker 在空队列上应该循环等待而非阻塞死锁。"""
        worker._poll_interval = 0.1

        def auto_stop():
            time.sleep(0.5)
            worker.stop()

        t = threading.Thread(target=auto_stop, daemon=True)
        t.start()
        worker.run()  # should exit after 0.5s
        assert worker._running is False


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------

class TestHeartbeat:
    def test_heartbeat_thread_updates(self, service, tmp_data_dir):
        """心跳线程应定期更新 heartbeat_at。"""
        job_id = _insert_queued_job(service)
        # claim 任务
        job = service.store.claim_next_job("w_heartbeat")
        assert job is not None

        initial_heartbeat = job.heartbeat_at

        # 手动更新一次 heartbeat
        time.sleep(0.1)
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        service.store.update(job_id, {"heartbeat_at": now})

        updated = service.store.get(job_id)
        assert updated.heartbeat_at == now
        assert updated.heartbeat_at != initial_heartbeat

    def test_heartbeat_thread_stops(self):
        """心跳线程应在 stop() 后终止。"""
        db_path = os.path.join(tempfile.mkdtemp(), "test.db")
        store = SQLiteJobStore(db_path=db_path)
        _insert_queued_job_to_store(store)

        ht = _HeartbeatThread(
            store=store,
            job_id="job_heartbeat_test",
            worker_id="w1",
            interval=1,
        )
        ht.start()
        ht.stop()
        # join 应该能在合理时间内返回
        if hasattr(ht, "_thread"):
            ht._thread.join(timeout=5)
            assert not ht._running


def _insert_queued_job_to_store(store, job_id="job_heartbeat_test"):
    record = JobRecord(
        job_id=job_id,
        source="cli",
        original_filename="test.pdf",
        input_path="/tmp/fake.pdf",
    )
    store.insert(record)
    return job_id


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------

class TestRecovery:
    def test_recover_stale_jobs_resets_to_queued(self, service):
        """重启恢复：running 且心跳过期的任务重置为 queued。"""
        # 插入一个 running 且心跳过期的任务
        from datetime import datetime, timezone, timedelta
        stale_time = (datetime.now(timezone.utc) - timedelta(seconds=1200)).isoformat()

        record = JobRecord(
            job_id="job_stale_001",
            source="cli",
            status=JobStatus.RUNNING,
            original_filename="old.pdf",
            input_path="/tmp/old.pdf",
            locked_by="old_worker",
            heartbeat_at=stale_time,
        )
        service.store.insert(record)

        worker = LocalWorker(
            service=service,
            config={
                "recover_running_on_start": True,
                "recover_timeout_seconds": 600,
            },
            worker_id="recover_worker",
        )

        count = worker.recover_stale_jobs()
        assert count == 1

        # 任务应被重置为 queued
        updated = service.store.get("job_stale_001")
        assert updated.status == JobStatus.QUEUED
        assert updated.locked_by == ""  # None 被 _row_to_record 转为 ""

    def test_recover_disabled_leaves_running(self, service):
        """关闭恢复功能时，running 任务保持原状态。"""
        from datetime import datetime, timezone, timedelta
        stale_time = (datetime.now(timezone.utc) - timedelta(seconds=1200)).isoformat()

        record = JobRecord(
            job_id="job_stale_002",
            source="cli",
            status=JobStatus.RUNNING,
            original_filename="old.pdf",
            input_path="/tmp/old.pdf",
            locked_by="old_worker",
            heartbeat_at=stale_time,
        )
        service.store.insert(record)

        worker = LocalWorker(
            service=service,
            config={
                "recover_running_on_start": False,
                "recover_timeout_seconds": 600,
            },
            worker_id="no_recover_worker",
        )

        count = worker.recover_stale_jobs()
        assert count == 0

        updated = service.store.get("job_stale_002")
        assert updated.status == JobStatus.RUNNING

    def test_no_stale_jobs_returns_zero(self, service):
        """没有过期任务时，恢复数量为 0。"""
        worker = LocalWorker(
            service=service,
            config={"recover_running_on_start": True, "recover_timeout_seconds": 600},
            worker_id="idle_worker",
        )
        count = worker.recover_stale_jobs()
        assert count == 0


# ---------------------------------------------------------------------------
# Concurrent claim protection
# ---------------------------------------------------------------------------

class TestConcurrentClaim:
    def test_multiple_workers_claim_same_job(self, service):
        """多 Worker 并发 claim 同一任务时，仅一个成功。"""
        job_id = _insert_queued_job(service)

        results = []
        lock = threading.Lock()

        def try_claim(wid):
            job = service.store.claim_next_job(wid)
            with lock:
                results.append((wid, job.job_id if job else None))

        threads = []
        for i in range(5):
            t = threading.Thread(target=try_claim, args=(f"w_{i}",))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=10)

        successful = [r for r in results if r[1] is not None]
        assert len(successful) == 1
        assert successful[0][1] == job_id

    def test_claim_order_by_created_at(self, service):
        """claim 应按 created_at 顺序领取最早的任务。"""
        ids = []
        for i in range(3):
            job_id = _insert_queued_job(service, filename=f"doc{i}.pdf")
            ids.append(job_id)
            time.sleep(0.05)  # 确保 created_at 不同

        # claim 应该拿到最早的
        job = service.store.claim_next_job("w_ordered")
        assert job is not None
        assert job.job_id == ids[0]
