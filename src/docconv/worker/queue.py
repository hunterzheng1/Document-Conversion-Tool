"""JobQueue 抽象：Protocol + 内存实现（为 RQ/Celery 预留）。"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

from docconv.service.job_models import JobRecord


# ---------------------------------------------------------------------------
# JobQueue Protocol（结构子类型）
# ---------------------------------------------------------------------------

@runtime_checkable
class JobQueue(Protocol):
    """队列抽象，Worker 通过该接口与任务队列交互。

    任何实现该 Protocol 的类（包括 RQ/Celery 包装器）均可作为 Worker
    的后端队列。
    """

    def enqueue(self, record: JobRecord) -> str:
        """将 job 加入队列。

        Returns:
            job_id
        """
        ...

    def dequeue(self, worker_id: str) -> JobRecord | None:
        """从队列中取出一个任务并标记为运行中。

        Args:
            worker_id: Worker 标识

        Returns:
            JobRecord 或 None（无任务）
        """
        ...

    def size(self) -> int:
        """返回队列中等待的任务数。"""
        ...


# ---------------------------------------------------------------------------
# InMemoryQueue：内存实现（默认/测试用）
# ---------------------------------------------------------------------------

class InMemoryQueue:
    """内存队列实现，主要用于测试和无 SQLite 场景。"""

    def __init__(self) -> None:
        self._queue: list[JobRecord] = []
        self._lock = threading.Lock()

    def enqueue(self, record: JobRecord) -> str:
        """将 job 加入队列。

        Args:
            record: JobRecord

        Returns:
            job_id
        """
        with self._lock:
            self._queue.append(record)
        return record.job_id

    def dequeue(self, worker_id: str) -> JobRecord | None:
        """从队列中取出一个任务。

        先进先出，按 created_at 排序。

        Args:
            worker_id: Worker 标识

        Returns:
            JobRecord 或 None
        """
        with self._lock:
            if not self._queue:
                return None
            record = self._queue.pop(0)
            # 标记为运行中（内存级别）
            record.status = "running"
            record.locked_by = worker_id
            record.heartbeat_at = time.strftime("%Y-%m-%dT%H:%M:%S")
            return record

    def size(self) -> int:
        """返回等待任务数。"""
        with self._lock:
            return len(self._queue)
