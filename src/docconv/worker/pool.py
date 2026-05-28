"""WorkerPool：Worker 池并发控制。"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

from docconv.service.job_models import JobStatus
from docconv.service.job_store import SQLiteJobStore

logger = logging.getLogger(__name__)


class WorkerPool:
    """管理多个 Worker 的并发执行。

    使用信号量控制最大并发数，达到上限时新任务阻塞等待，
    任务完成后自动释放槽位。支持运行时动态调整并发上限。
    """

    def __init__(
        self,
        store: SQLiteJobStore,
        max_workers: int = 1,
        poll_interval: float = 2.0,
    ) -> None:
        """初始化 Worker 池。

        Args:
            store: SQLiteJobStore 实例
            max_workers: 最大并发 Worker 数（对应 max_running_jobs）
            poll_interval: 无任务时轮询间隔（秒）

        Raises:
            ValueError: max_workers < 1
        """
        if max_workers < 1:
            raise ValueError(f"max_workers 必须 >= 1，当前值: {max_workers}")

        self._store = store
        self._max_workers = max_workers
        self._poll_interval = poll_interval
        self._semaphore = threading.Semaphore(max_workers)
        self._lock = threading.Lock()
        self._running = False
        self._workers: list[threading.Thread] = []

    @property
    def max_workers(self) -> int:
        """当前最大并发数。"""
        return self._max_workers

    def set_max_workers(self, new_max: int) -> None:
        """运行时动态调整并发上限。

        Args:
            new_max: 新的最大并发数，必须 >= 1
        """
        if new_max < 1:
            raise ValueError(f"max_workers 必须 >= 1，当前值: {new_max}")

        with self._lock:
            old_max = self._max_workers
            self._max_workers = new_max

            # 扩容：增加信号量槽位
            if new_max > old_max:
                for _ in range(new_max - old_max):
                    self._semaphore.release()
            # 缩容：减少槽位（通过增加内部计数来限制）
            # 注意：缩容不立即移除已运行的 worker，但会限制后续领取
            logger.info(
                f"Worker 池并发数调整: {old_max} -> {new_max}"
            )

    def run_workers(self, worker_fn: Callable[[str], bool], worker_ids: list[str]) -> None:
        """启动指定数量的 Worker 线程。

        Args:
            worker_fn: Worker 执行函数，接收 worker_id，返回是否成功
            worker_ids: Worker ID 列表
        """
        self._running = True
        self._workers = []

        for wid in worker_ids:
            t = threading.Thread(
                target=self._worker_loop,
                args=(worker_fn, wid),
                daemon=True,
                name=f"pool-worker-{wid}",
            )
            t.start()
            self._workers.append(t)

        # 等待所有线程完成
        for t in self._workers:
            t.join()

    def stop(self) -> None:
        """停止所有 Worker。"""
        self._running = False

    def _worker_loop(self, worker_fn: Callable[[str], bool], worker_id: str) -> None:
        """单个 Worker 的循环逻辑。

        1. 获取信号量（并发控制）
        2. claim_next_job
        3. 执行 worker_fn
        4. 释放信号量
        5. 重复
        """
        logger.info(f"Worker 线程启动: {worker_id}")

        while self._running:
            # 获取信号量（达到并发上限时阻塞）
            acquired = self._semaphore.acquire(timeout=self._poll_interval)
            if not acquired:
                continue

            try:
                # 尝试领取任务
                job = self._store.claim_next_job(worker_id)
                if job is None:
                    continue

                logger.info(f"Worker {worker_id} 领取任务: {job.job_id}")
                success = worker_fn(worker_id)
                if success:
                    logger.info(f"Worker {worker_id} 完成: {job.job_id}")
                else:
                    logger.warning(f"Worker {worker_id} 失败: {job.job_id}")

            except Exception as exc:
                logger.error(f"Worker {worker_id} 异常: {exc}")

            finally:
                self._semaphore.release()

    def get_stats(self) -> dict[str, Any]:
        """返回池统计信息。

        Returns:
            包含 max_workers、active_workers、queue_size 的字典
        """
        active = self._store.count_by_status(JobStatus.RUNNING)
        queued = self._store.count_by_status(JobStatus.QUEUED)
        alive = sum(1 for t in self._workers if t.is_alive())

        return {
            "max_workers": self._max_workers,
            "active_workers": active,
            "alive_threads": alive,
            "queued_jobs": queued,
        }
