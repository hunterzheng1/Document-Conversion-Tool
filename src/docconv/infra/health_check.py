"""服务健康检查器。

检查磁盘空间、job_store 可用性、缓存状态、Worker 心跳。
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class HealthComponent:
    name: str
    status: str  # "ok" / "degraded" / "error"
    message: str = ""


@dataclass
class HealthResult:
    overall: str  # "ok" / "degraded" / "error"
    components: list[HealthComponent]
    uptime_seconds: float = 0.0
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


# Worker 心跳数据模型
@dataclass
class WorkerHeartbeat:
    worker_id: str
    last_seen: float
    status: str = "running"
    current_job_id: str | None = None


class HealthChecker:
    """检查服务各组件健康状态。"""

    # 默认 Worker 心跳过期阈值（秒）
    DEFAULT_WORKER_STALE_SECONDS = 120

    def __init__(self, config: dict[str, Any] | None = None):
        self._config = config or {}
        self._started_at = time.time()
        self._worker_heartbeats: dict[str, WorkerHeartbeat] = {}
        self._worker_stale_seconds: int = self._config.get(
            "worker_stale_seconds", self.DEFAULT_WORKER_STALE_SECONDS,
        )

    def check(self) -> HealthResult:
        """执行全部健康检查。"""
        components = [
            self._check_disk_space(),
            self._check_job_store(),
            self._check_cache(),
            self._check_workers(),
        ]

        statuses = {c.status for c in components}
        if "error" in statuses:
            overall = "error"
        elif "degraded" in statuses:
            overall = "degraded"
        else:
            overall = "ok"

        return HealthResult(
            overall=overall,
            components=components,
            uptime_seconds=time.time() - self._started_at,
        )

    def _check_disk_space(self) -> HealthComponent:
        storage_root = self._config.get("storage_root", ".data/docconv")
        try:
            usage = shutil.disk_usage(storage_root)
            free_pct = usage.free / usage.total * 100
            if free_pct < 5:
                return HealthComponent("disk", "error", f"磁盘空间不足: {free_pct:.1f}% 剩余")
            elif free_pct < 15:
                return HealthComponent("disk", "degraded", f"磁盘空间偏低: {free_pct:.1f}% 剩余")
            return HealthComponent("disk", "ok", f"{free_pct:.1f}% 剩余")
        except OSError as e:
            return HealthComponent("disk", "error", f"无法检查磁盘: {e}")

    def _check_job_store(self) -> HealthComponent:
        storage_root = self._config.get("storage_root", ".data/docconv")
        db_path = f"{storage_root}/job_store.sqlite3"
        try:
            import sqlite3
            conn = sqlite3.connect(db_path)
            conn.execute("SELECT 1")
            conn.close()
            return HealthComponent("job_store", "ok", "SQLite 可用")
        except Exception as e:
            return HealthComponent("job_store", "error", f"SQLite 不可用: {e}")

    def _check_cache(self) -> HealthComponent:
        cache_dir = self._config.get("cache_dir", ".cache/docconv")
        try:
            import os
            if os.path.isdir(cache_dir):
                return HealthComponent("cache", "ok", "缓存目录存在")
            return HealthComponent("cache", "degraded", "缓存目录缺失")
        except Exception as e:
            return HealthComponent("cache", "error", str(e))

    # ---- Worker 心跳管理 ----

    def record_heartbeat(self, worker_id: str, current_job_id: str | None = None) -> None:
        """记录 Worker 心跳。"""
        self._worker_heartbeats[worker_id] = WorkerHeartbeat(
            worker_id=worker_id,
            last_seen=time.time(),
            status="running",
            current_job_id=current_job_id,
        )

    def remove_worker(self, worker_id: str) -> None:
        """移除 Worker（下线）。"""
        self._worker_heartbeats.pop(worker_id, None)

    def get_workers(self) -> dict[str, WorkerHeartbeat]:
        """获取全部 Worker 心跳数据。"""
        return dict(self._worker_heartbeats)

    def get_active_worker_count(self) -> int:
        """获取活跃 Worker 数量（心跳在阈值内）。"""
        now = time.time()
        count = 0
        for wb in self._worker_heartbeats.values():
            if now - wb.last_seen < self._worker_stale_seconds:
                count += 1
        return count

    def _check_workers(self) -> HealthComponent:
        """检查 Worker 心跳健康状态。"""
        if not self._worker_heartbeats:
            return HealthComponent("worker", "ok", "无活跃 Worker")

        now = time.time()
        stale_workers = []
        max_age = 0.0

        for worker_id, wb in self._worker_heartbeats.items():
            age = now - wb.last_seen
            max_age = max(max_age, age)
            if age >= self._worker_stale_seconds:
                stale_workers.append(worker_id)

        if stale_workers:
            return HealthComponent(
                "worker", "degraded",
                f"{len(stale_workers)} 个 Worker 心跳超时: {', '.join(stale_workers)}",
            )

        return HealthComponent(
            "worker", "ok",
            f"{len(self._worker_heartbeats)} 个 Worker 活跃, 最大心跳延迟 {max_age:.0f}s",
        )
