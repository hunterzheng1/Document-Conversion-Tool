"""健康检查模块测试。"""

import os
import tempfile
import time
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from docconv.infra.health_check import (
    HealthChecker,
    HealthComponent,
    HealthResult,
    WorkerHeartbeat,
)


class TestHealthChecker:
    """测试 HealthChecker 基础功能。"""

    def test_check_all_components(self, tmp_path):
        """全部检查应返回 ok 状态（假设有磁盘空间）。"""
        config = {
            "storage_root": str(tmp_path),
            "cache_dir": str(tmp_path / "cache"),
        }
        os.makedirs(tmp_path / "cache", exist_ok=True)
        # 创建 job_store 数据库
        import sqlite3
        db_path = str(tmp_path / "job_store.sqlite3")
        conn = sqlite3.connect(db_path)
        conn.execute("SELECT 1")
        conn.close()

        checker = HealthChecker(config=config)
        result = checker.check()
        assert result.overall in ("ok", "degraded")  # 取决于磁盘空间
        assert len(result.components) == 4  # disk, job_store, cache, worker

    def test_no_workers_returns_ok(self):
        """无 Worker 时 worker 组件应为 ok。"""
        checker = HealthChecker()
        result = checker.check()
        worker_comp = next(c for c in result.components if c.name == "worker")
        assert worker_comp.status == "ok"

    def test_uptime_positive(self):
        """运行时间应为正数。"""
        checker = HealthChecker()
        result = checker.check()
        assert result.uptime_seconds >= 0


class TestDiskCheck:
    """测试磁盘空间检查。"""

    def test_root_check(self):
        checker = HealthChecker(config={"storage_root": "/"})
        comp = checker._check_disk_space()
        assert comp.name == "disk"
        assert comp.status in ("ok", "degraded")

    def test_nonexistent_path(self):
        checker = HealthChecker(config={"storage_root": "/nonexistent/path/xyz"})
        comp = checker._check_disk_space()
        assert comp.status == "error"


class TestJobStoreCheck:
    """测试 job_store 检查。"""

    def test_valid_sqlite(self, tmp_path):
        import sqlite3
        db_path = str(tmp_path / "job_store.sqlite3")
        conn = sqlite3.connect(db_path)
        conn.execute("SELECT 1")
        conn.close()

        checker = HealthChecker(config={"storage_root": str(tmp_path)})
        comp = checker._check_job_store()
        assert comp.status == "ok"

    def test_missing_sqlite(self, tmp_path):
        checker = HealthChecker(config={"storage_root": str(tmp_path)})
        comp = checker._check_job_store()
        # SQLite 会自动创建文件，所以不会 error
        assert comp.status == "ok"


class TestCacheCheck:
    """测试缓存检查。"""

    def test_cache_exists(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        os.makedirs(cache_dir, exist_ok=True)
        checker = HealthChecker(config={"cache_dir": cache_dir})
        comp = checker._check_cache()
        assert comp.status == "ok"

    def test_cache_missing(self):
        checker = HealthChecker(config={"cache_dir": "/nonexistent/cache/dir"})
        comp = checker._check_cache()
        assert comp.status == "degraded"


class TestWorkerHeartbeat:
    """测试 Worker 心跳管理。"""

    def test_record_heartbeat(self):
        checker = HealthChecker()
        checker.record_heartbeat("w1", "job_001")
        workers = checker.get_workers()
        assert "w1" in workers
        assert workers["w1"].current_job_id == "job_001"

    def test_remove_worker(self):
        checker = HealthChecker()
        checker.record_heartbeat("w1")
        checker.record_heartbeat("w2")
        checker.remove_worker("w1")
        workers = checker.get_workers()
        assert "w1" not in workers
        assert "w2" in workers

    def test_remove_nonexistent_worker(self):
        checker = HealthChecker()
        checker.remove_worker("nonexistent")  # 不应抛异常

    def test_active_worker_count(self):
        checker = HealthChecker()
        checker.record_heartbeat("w1")
        checker.record_heartbeat("w2")
        assert checker.get_active_worker_count() == 2

    def test_stale_worker_not_counted(self):
        checker = HealthChecker(config={"worker_stale_seconds": 1})
        checker.record_heartbeat("w1")
        # 手动设置心跳为旧时间
        checker._worker_heartbeats["w1"].last_seen = time.time() - 10
        assert checker.get_active_worker_count() == 0


class TestWorkerHealthCheck:
    """测试 Worker 健康检查。"""

    def test_fresh_workers_ok(self):
        checker = HealthChecker()
        checker.record_heartbeat("w1")
        checker.record_heartbeat("w2")
        result = checker.check()
        worker_comp = next(c for c in result.components if c.name == "worker")
        assert worker_comp.status == "ok"

    def test_stale_workers_degraded(self):
        checker = HealthChecker(config={"worker_stale_seconds": 1})
        checker.record_heartbeat("w1")
        # 手动设置为过期
        checker._worker_heartbeats["w1"].last_seen = time.time() - 10
        result = checker.check()
        worker_comp = next(c for c in result.components if c.name == "worker")
        assert worker_comp.status == "degraded"
        assert "w1" in worker_comp.message

    def test_overall_degraded_when_worker_stale(self):
        """Worker 心跳超时应使整体降级。"""
        checker = HealthChecker(config={"worker_stale_seconds": 1, "storage_root": "/tmp"})
        checker.record_heartbeat("w1")
        checker._worker_heartbeats["w1"].last_seen = time.time() - 10
        result = checker.check()
        assert result.overall == "degraded"


class TestHealthResult:
    """测试 HealthResult 数据结构。"""

    def test_timestamp_auto_set(self):
        result = HealthResult(
            overall="ok",
            components=[HealthComponent("disk", "ok")],
        )
        assert result.timestamp > 0

    def test_custom_timestamp(self):
        ts = 1000000.0
        result = HealthResult(
            overall="ok",
            components=[],
            timestamp=ts,
        )
        assert result.timestamp == ts
