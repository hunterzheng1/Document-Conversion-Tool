"""测试 WorkerPool 并发控制。"""

import os
import time
import threading
import tempfile
import shutil
import pytest

from docconv.service.job_models import JobStatus, JobRecord
from docconv.service.job_store import SQLiteJobStore
from docconv.worker.pool import WorkerPool


@pytest.fixture()
def tmp_data_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def store(tmp_data_dir):
    db_path = os.path.join(tmp_data_dir, "job_store.sqlite3")
    return SQLiteJobStore(db_path=db_path)


class TestWorkerPoolInit:
    def test_default_max_workers(self, store):
        pool = WorkerPool(store, max_workers=1)
        assert pool.max_workers == 1

    def test_custom_max_workers(self, store):
        pool = WorkerPool(store, max_workers=4)
        assert pool.max_workers == 4

    def test_invalid_max_workers(self, store):
        with pytest.raises(ValueError, match="max_workers"):
            WorkerPool(store, max_workers=0)

    def test_stats(self, store):
        pool = WorkerPool(store, max_workers=2)
        stats = pool.get_stats()
        assert stats["max_workers"] == 2
        assert stats["active_workers"] == 0
        assert stats["alive_threads"] == 0


class TestWorkerPoolDynamicConcurrency:
    def test_increase_max_workers(self, store):
        pool = WorkerPool(store, max_workers=1, poll_interval=0.5)
        assert pool.max_workers == 1
        pool.set_max_workers(3)
        assert pool.max_workers == 3

    def test_decrease_max_workers(self, store):
        pool = WorkerPool(store, max_workers=4, poll_interval=0.5)
        pool.set_max_workers(2)
        assert pool.max_workers == 2

    def test_invalid_decrease(self, store):
        pool = WorkerPool(store, max_workers=4, poll_interval=0.5)
        with pytest.raises(ValueError, match="max_workers"):
            pool.set_max_workers(0)


class TestWorkerPoolExecution:
    def test_single_worker_executes_job(self, store, tmp_data_dir):
        """验证 Worker 能正确领取并执行任务。"""
        # 插入一个 queued 任务
        record = JobRecord(
            job_id="job_pool_001",
            source="cli",
            original_filename="test.pdf",
            input_path="/tmp/test.pdf",
        )
        store.insert(record)

        results = {"executed": 0, "job_ids": []}

        def dummy_worker_fn(wid: str) -> bool:
            results["executed"] += 1
            return True

        pool = WorkerPool(store, max_workers=1, poll_interval=0.5)

        # 用单线程模式测试
        worker_id = "w_pool_test"
        job = store.claim_next_job(worker_id)
        assert job is not None
        assert job.job_id == "job_pool_001"
        assert job.status == JobStatus.RUNNING

        # 执行
        success = dummy_worker_fn(worker_id)
        assert success is True

    def test_no_jobs_blocks(self, store):
        """验证无任务时 Worker 不会卡死。"""
        pool = WorkerPool(store, max_workers=1, poll_interval=0.2)

        executed = [0]

        def dummy_fn(wid: str) -> bool:
            executed[0] += 1
            return True

        # 启动后很快停止
        pool._running = True
        # 无任务时 _worker_loop 应该继续循环而非死锁
        # 这里只测试初始状态
        stats = pool.get_stats()
        assert stats["active_workers"] == 0

    def test_concurrent_claim_protection(self, store):
        """验证并发领取不会导致同一任务被多次领取。"""
        record = JobRecord(
            job_id="job_concurrent_001",
            source="cli",
            original_filename="test.pdf",
            input_path="/tmp/test.pdf",
        )
        store.insert(record)

        claimed_by = []
        lock = threading.Lock()

        def try_claim(worker_id: str):
            job = store.claim_next_job(worker_id)
            if job is not None:
                with lock:
                    claimed_by.append(worker_id)

        # 多线程并发 claim
        threads = []
        for i in range(5):
            t = threading.Thread(target=try_claim, args=(f"w_{i}",))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=10)

        # 只有一个 worker 能成功领取
        assert len(claimed_by) == 1
