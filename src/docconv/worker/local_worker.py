"""LocalWorker：单机 Worker，轮询并执行 queued job。"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from docconv.core.converter import DocumentConverter
from docconv.core.types import ConversionConfig, ConversionResult
from docconv.service.conversion_job_service import ConversionJobService, DEFAULT_JOB_CONFIG
from docconv.service.job_models import JobRecord, JobStatus, ServiceError, ErrorCodes
from docconv.service.job_store import SQLiteJobStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LocalWorker
# ---------------------------------------------------------------------------

class LocalWorker:
    """本地 Worker：轮询 SQLite 队列、执行转换、更新状态。

    主循环流程：
    1. claim_next_job(worker_id) 原子领取任务
    2. 获取到 job 则执行转换
    3. 未获取到则等待 poll_interval 秒后重试

    特性：
    - 启动恢复（running 且心跳过期的任务重置为 queued）
    - 心跳更新（执行转换期间定期更新 heartbeat_at）
    - 并发控制（max_running_jobs）
    - 优雅停止（stop() 方法）
    """

    def __init__(
        self,
        service: ConversionJobService,
        config: dict[str, Any] | None = None,
        worker_id: str | None = None,
    ):
        """初始化 Worker。

        Args:
            service: ConversionJobService 实例
            config: Worker 配置（覆盖默认）
            worker_id: 自定义 Worker ID，不提供则自动生成
        """
        self._service = service
        self._store = service.store

        self._config = {**DEFAULT_JOB_CONFIG}
        if config:
            self._config.update(config)

        self._worker_id = worker_id or self._generate_worker_id()
        self._running = False
        self._heartbeat_interval = 30  # 心跳间隔（秒）
        self._poll_interval = int(
            self._config.get("worker_poll_interval_seconds", 2)
        )
        self._max_running = int(self._config.get("max_running_jobs", 1))
        self._recover_timeout = int(
            self._config.get("recover_timeout_seconds", 600)
        )
        self._recover_on_start = bool(
            self._config.get("recover_running_on_start", True)
        )

    @staticmethod
    def _generate_worker_id() -> str:
        """生成 Worker ID: worker_<pid>_<timestamp>。"""
        pid = os.getpid()
        ts = int(time.time())
        return f"worker_{pid}_{ts}"

    @property
    def worker_id(self) -> str:
        """Worker 唯一标识。"""
        return self._worker_id

    # ---- 启动恢复 ----

    def recover_stale_jobs(self) -> int:
        """服务重启后恢复运行中但心跳过期的任务。

        扫描 status='running' 且 heartbeat_at 超过 recover_timeout 的任务。
        根据 recover_running_on_start 配置：
        - True: 重置为 queued（可重试）
        - False: 标记为 failed

        Returns:
            恢复的任务数量
        """
        if not self._recover_on_start:
            return 0

        stale_jobs = self._store.list_stale_running(self._recover_timeout)
        if not stale_jobs:
            return 0

        count = 0
        for job in stale_jobs:
            logger.info(
                f"恢复任务: {job.job_id} (心跳过期于 {job.heartbeat_at})"
            )
            try:
                if self._recover_on_start:
                    # 重置为 queued，清除 locked_by
                    self._store.update(job.job_id, {
                        "status": JobStatus.QUEUED,
                        "locked_by": None,
                        "heartbeat_at": None,
                    })
                else:
                    self._service.fail_job(
                        job.job_id,
                        error_type="worker_restart",
                        error_message="Worker 重启，任务被标记为失败",
                    )
                count += 1
            except ServiceError as exc:
                logger.error(f"恢复任务失败: {job.job_id} [{exc.code}] {exc.message}")

        logger.info(f"恢复完成: {count}/{len(stale_jobs)} 个任务")
        return count

    # ---- 主循环 ----

    def run(self) -> None:
        """启动 Worker 主循环（同步版本）。

        先执行启动恢复，然后进入轮询循环：
        1. 检查当前 running 任务数是否达到上限
        2. claim_next_job
        3. 有任务则执行，无任务则等待 poll_interval
        """
        self._running = True
        logger.info(f"Worker 启动: {self._worker_id}")

        # 启动恢复
        recovered = self.recover_stale_jobs()
        if recovered > 0:
            logger.info(f"已恢复 {recovered} 个任务")

        while self._running:
            # 检查并发限制
            current_running = self._store.count_by_status(JobStatus.RUNNING)
            if current_running >= self._max_running:
                logger.debug(
                    f"并发已达上限 ({current_running}/{self._max_running})，"
                    f"等待 {self._poll_interval}s"
                )
                time.sleep(self._poll_interval)
                continue

            # 尝试领取任务
            job = self._store.claim_next_job(self._worker_id)
            if job is None:
                logger.debug(f"无可用任务，等待 {self._poll_interval}s")
                time.sleep(self._poll_interval)
                continue

            logger.info(f"领取任务: {job.job_id}")
            self._execute_job(job)

        logger.info(f"Worker 已停止: {self._worker_id}")

    def stop(self) -> None:
        """停止 Worker 主循环。"""
        self._running = False

    # ---- 任务执行 ----

    def _execute_job(self, job: JobRecord) -> None:
        """执行一个转换任务。

        Args:
            job: 已 claim 的 JobRecord（status=running）
        """
        logger.info(f"开始执行: {job.job_id} (input={job.input_path})")

        try:
            # 运行转换（异步）
            result = self._run_conversion(job)

            # 转换成功
            self._service.complete_job(
                job.job_id,
                output_path=job.output_path,
                report_path=job.report_path,
            )
            self._service.update_progress(job.job_id, {
                "total_pages": result.total_pages,
                "completed_pages": result.success_pages,
                "failed_pages": result.failed_pages,
                "duration_seconds": result.duration_seconds,
                "status": "completed",
            })
            logger.info(
                f"任务完成: {job.job_id} "
                f"({result.success_pages}/{result.total_pages} 页, "
                f"{result.duration_seconds:.1f}s)"
            )

        except Exception as exc:
            error_type = type(exc).__name__
            error_message = str(exc)
            logger.error(
                f"任务失败: {job.job_id} [{error_type}] {error_message}"
            )
            try:
                self._service.fail_job(
                    job.job_id,
                    error_type=error_type,
                    error_message=error_message,
                )
            except ServiceError as svc_exc:
                logger.error(
                    f"标记失败失败: {job.job_id} "
                    f"[{svc_exc.code}] {svc_exc.message}"
                )

    def _run_conversion(self, job: JobRecord) -> ConversionResult:
        """运行 DocumentConverter.convert() 异步调用。

        Args:
            job: JobRecord

        Returns:
            ConversionResult

        Raises:
            转换过程中的任何异常
        """
        # 构建转换配置
        options = job.options_json or {}
        converter_config = {
            "cache": {},
            "state": {
                "state_dir": str(
                    Path(job.input_path).parent.parent / "state"
                ),
            },
            "parallel": options.get("parallel", 1),
            "verbose": options.get("verbose", False),
            "sensitive_mode": options.get("sensitive_mode", False),
        }

        # 创建转换器
        converter = DocumentConverter(converter_config)

        # 启动心跳线程
        heartbeat_thread = _HeartbeatThread(
            store=self._store,
            job_id=job.job_id,
            worker_id=self._worker_id,
            interval=self._heartbeat_interval,
        )
        heartbeat_thread.start()

        try:
            # 运行异步转换
            result = asyncio.run(converter.convert(job.input_path))
            return result
        finally:
            heartbeat_thread.stop()


# ---------------------------------------------------------------------------
# 心跳线程
# ---------------------------------------------------------------------------

class _HeartbeatThread:
    """后台心跳更新线程，定期更新 running job 的 heartbeat_at。"""

    def __init__(
        self,
        store: SQLiteJobStore,
        job_id: str,
        worker_id: str,
        interval: int = 30,
    ):
        self._store = store
        self._job_id = job_id
        self._worker_id = worker_id
        self._interval = interval
        self._stop_event = asyncio.Event() if hasattr(asyncio, 'Event') else None
        self._running = True

    def start(self) -> None:
        """启动心跳线程（后台守护）。"""
        import threading

        def _loop():
            while self._running:
                time.sleep(self._interval)
                if self._running:
                    try:
                        now = datetime.now(timezone.utc).isoformat()
                        self._store.update(self._job_id, {
                            "heartbeat_at": now,
                        })
                        logger.debug(
                            f"心跳更新: {self._job_id} @ {now}"
                        )
                    except ServiceError:
                        logger.warning(
                            f"心跳更新失败: {self._job_id}"
                        )
                    except Exception:
                        logger.exception(
                            f"心跳更新异常: {self._job_id}"
                        )

        self._thread = threading.Thread(
            target=_loop, daemon=True, name=f"heartbeat-{self._job_id}"
        )
        self._thread.start()

    def stop(self) -> None:
        """停止心跳线程。"""
        self._running = False
        if hasattr(self, "_thread"):
            self._thread.join(timeout=5)
