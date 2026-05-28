"""ConversionJobService：Job 生命周期门面。"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from .job_models import (
    JobRecord,
    JobStatus,
    ConversionRequest,
    ServiceError,
    ErrorCodes,
)
from .job_store import SQLiteJobStore
from .workspace import JobWorkspace
from docconv.infra.logger import log_job_event

logger = logging.getLogger(__name__)


def _get_file_size(path: str) -> int:
    """获取文件大小（字节），失败返回 0。"""
    try:
        return Path(path).stat().st_size
    except (OSError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# Job 配置
# ---------------------------------------------------------------------------

DEFAULT_JOB_CONFIG = {
    "storage_root": ".data/docconv",
    "retention_hours": 24,
    "max_running_jobs": 1,
    "max_queued_jobs": 20,
    "worker_poll_interval_seconds": 2,
    "enabled": True,
    "recover_running_on_start": True,
    "cleanup_expired": True,
    "recover_timeout_seconds": 600,
}


class ConversionJobService:
    """Job 生命周期管理门面。

    职责：
    - create_job: 校验请求、检查队列上限、创建 workspace、复制输入文件、插入 SQLite 记录
    - get_job / cancel_job: 查询与取消
    - complete_job / fail_job / update_progress: 终态与进度更新
    """

    def __init__(self, config: dict[str, Any] | None = None, store: SQLiteJobStore | None = None):
        """初始化。

        Args:
            config: Job 配置（覆盖默认值）
            store: SQLiteJobStore 实例，不提供则自动创建
        """
        self._config = {**DEFAULT_JOB_CONFIG}
        if config:
            self._config.update(config)

        self._storage_root = Path(self._config["storage_root"])
        self._storage_root.mkdir(parents=True, exist_ok=True)

        self._store = store or SQLiteJobStore(
            self._storage_root / "job_store.sqlite3"
        )

    # ---- 创建 ----

    def create_job(self, request: ConversionRequest) -> dict[str, str]:
        """创建一个新的 queued job。

        流程：
        1. 校验 request 参数
        2. 检查队列上限
        3. 生成 job_id 和 workspace
        4. 复制输入文件到 workspace/input/
        5. 插入 SQLite job 记录（status=queued）

        Args:
            request: 统一转换请求

        Returns:
            {"job_id": ..., "status": "queued"}

        Raises:
            ServiceError: 队列已满 (SVC1002) 或创建失败 (SVC5001)
        """
        # 1) 校验请求
        request.validate()

        # 2) 检查队列上限
        max_queued = int(self._config["max_queued_jobs"])
        queued_count = self._store.count_by_status(JobStatus.QUEUED)
        if queued_count >= max_queued:
            raise ServiceError(
                ErrorCodes.SVC2003,
                f"队列已满 ({queued_count}/{max_queued})",
            )

        # 3) 生成 job_id 和 workspace
        job_id = JobRecord.generate_job_id()
        retention_hours = int(self._config["retention_hours"])
        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(hours=retention_hours)).isoformat()

        workspace = JobWorkspace(job_id, self._storage_root)

        # 4) 复制输入文件到 workspace/input/
        try:
            src = Path(request.input_file_path)
            dst_name = request.original_filename or src.name
            dst = workspace.resolve("input", dst_name)
            shutil.copy2(str(src), str(dst))
        except (OSError, shutil.Error, ValueError) as exc:
            # 复制失败，清理 workspace
            workspace.cleanup()
            raise ServiceError(
                ErrorCodes.SVC5001,
                f"复制输入文件失败: {exc}",
            )

        # 5) 插入 SQLite job 记录
        input_path = str(workspace.resolve("input", dst_name))
        output_path = str(workspace.resolve("output", "result.md"))
        report_path = str(workspace.resolve("output", "report.md"))

        record = JobRecord(
            job_id=job_id,
            source=request.source,
            status=JobStatus.QUEUED,
            original_filename=request.original_filename,
            input_path=input_path,
            output_path=output_path,
            report_path=report_path,
            instruction=request.instruction,
            options_json=request.options,
            progress_json={"total_pages": 0, "completed_pages": 0, "failed_pages": 0},
            expires_at=expires_at,
        )

        try:
            self._store.insert(record)
        except ServiceError:
            # 插入失败，清理 workspace
            workspace.cleanup()
            raise

        logger.info(f"Job 已创建: {job_id} (source={request.source})")
        log_job_event("created", job_id, request.source, status=JobStatus.QUEUED, extra={"file_size": _get_file_size(request.input_file_path)})
        return {"job_id": job_id, "status": JobStatus.QUEUED}

    # ---- 查询与取消 ----

    def get_job(self, job_id: str) -> JobRecord:
        """查询 job 记录。

        Args:
            job_id: 任务 ID

        Returns:
            JobRecord

        Raises:
            ServiceError: job 不存在 (SVC2001)
        """
        record = self._store.get(job_id)
        if record is None:
            raise ServiceError(
                ErrorCodes.SVC2001,
                f"job 不存在: {job_id}",
            )
        return record

    def cancel_job(self, job_id: str) -> dict[str, str]:
        """取消 queued 或 running 的 job。

        Args:
            job_id: 任务 ID

        Returns:
            {"job_id": ..., "status": "cancelled"}

        Raises:
            ServiceError: job 不存在 (SVC2001) / 非法状态转换 (SVC2002)
        """
        record = self.get_job(job_id)  # 可能抛 SVC2001

        if not JobStatus.can_transition(record.status, JobStatus.CANCELLED):
            raise ServiceError(
                ErrorCodes.SVC2002,
                f"无法从状态 '{record.status}' 转换到 'cancelled' (job: {job_id})",
            )

        self._store.update(job_id, {
            "status": JobStatus.CANCELLED,
        })
        logger.info(f"Job 已取消: {job_id}")
        log_job_event("cancelled", job_id, record.source, status=JobStatus.CANCELLED)
        return {"job_id": job_id, "status": JobStatus.CANCELLED}

    # ---- 终态与进度 ----

    def complete_job(
        self,
        job_id: str,
        output_path: str = "",
        report_path: str = "",
    ) -> dict[str, str]:
        """标记 job 为 succeeded。

        Args:
            job_id: 任务 ID
            output_path: 输出文件路径（需在 workspace 内）
            report_path: 报告文件路径（需在 workspace 内）

        Returns:
            {"job_id": ..., "status": "succeeded"}

        Raises:
            ServiceError: job 不存在 (SVC2001) / 非法状态 (SVC2002)
        """
        record = self.get_job(job_id)

        if not JobStatus.can_transition(record.status, JobStatus.SUCCEEDED):
            raise ServiceError(
                ErrorCodes.SVC2002,
                f"无法从状态 '{record.status}' 转换到 'succeeded' (job: {job_id})",
            )

        fields: dict[str, Any] = {"status": JobStatus.SUCCEEDED}
        if output_path:
            self._validate_workspace_path(record, output_path)
            fields["output_path"] = output_path
        if report_path:
            self._validate_workspace_path(record, report_path)
            fields["report_path"] = report_path

        self._store.update(job_id, fields)
        logger.info(f"Job 已完成: {job_id}")
        log_job_event("completed", job_id, record.source, status=JobStatus.SUCCEEDED)
        return {"job_id": job_id, "status": JobStatus.SUCCEEDED}

    def fail_job(
        self,
        job_id: str,
        error_type: str = "",
        error_message: str = "",
    ) -> dict[str, str]:
        """标记 job 为 failed，对错误信息进行脱敏。

        Args:
            job_id: 任务 ID
            error_type: 错误类型（脱敏后）
            error_message: 错误信息（脱敏后，<= 2000 字符）

        Returns:
            {"job_id": ..., "status": "failed"}

        Raises:
            ServiceError: job 不存在 (SVC2001) / 非法状态 (SVC2002)
        """
        record = self.get_job(job_id)

        if not JobStatus.can_transition(record.status, JobStatus.FAILED):
            raise ServiceError(
                ErrorCodes.SVC2002,
                f"无法从状态 '{record.status}' 转换到 'failed' (job: {job_id})",
            )

        # 脱敏：移除可能的 API Key 等敏感信息
        sanitized_msg = self._sanitize_error_message(error_message)

        self._store.update(job_id, {
            "status": JobStatus.FAILED,
            "error_type": error_type,
            "error_message": sanitized_msg,
        })
        logger.warning(f"Job 失败: {job_id} ({error_type})")
        log_job_event("failed", job_id, record.source, status=JobStatus.FAILED, extra={"error_type": error_type})
        return {"job_id": job_id, "status": JobStatus.FAILED}

    def update_progress(
        self, job_id: str, progress: dict[str, Any]
    ) -> None:
        """更新 job 进度。

        Args:
            job_id: 任务 ID
            progress: 进度数据字典
        """
        self._store.update(job_id, {"progress_json": progress})

    # ---- 内部方法 ----

    @staticmethod
    def _sanitize_error_message(message: str) -> str:
        """对错误消息进行脱敏，移除可能的 API Key 等敏感信息。

        Args:
            message: 原始错误消息

        Returns:
            脱敏后的消息，截断到 2000 字符
        """
        # 常见 API Key 模式
        import re
        patterns = [
            r"(sk-[A-Za-z0-9]{20,})",  # OpenAI style
            r"(anthropic-[A-Za-z0-9]{20,})",  # Anthropic style
            r"(Bearer [A-Za-z0-9._-]+)",  # Bearer token
            r"(api[_-]?key[=:]\s*\S+)",  # api_key=xxx
        ]
        for pattern in patterns:
            message = re.sub(pattern, "***REDACTED***", message, flags=re.IGNORECASE)

        # 截断到 2000 字符
        if len(message) > 2000:
            message = message[:2000] + "..."

        return message

    @staticmethod
    def _validate_workspace_path(record: JobRecord, path: str) -> None:
        """验证路径在 job workspace 内。

        Args:
            record: JobRecord（包含 input_path 用于推导 workspace 根目录）
            path: 待验证路径

        Raises:
            ServiceError: 路径不在 workspace 内 (SVC1001)
        """
        # 从 input_path 推导 workspace 根目录
        # input_path 格式: {storage_root}/jobs/{job_id}/input/filename
        workspace_root = Path(record.input_path).parent.parent
        resolved = Path(path).resolve()

        if not str(resolved).startswith(str(workspace_root)):
            raise ServiceError(
                ErrorCodes.SVC1001,
                f"路径不在 workspace 内: {path}",
            )

    # ---- 配置属性 ----

    @property
    def config(self) -> dict[str, Any]:
        """返回当前 job 配置副本。"""
        return dict(self._config)

    @property
    def store(self) -> SQLiteJobStore:
        """返回底层 SQLiteJobStore 实例。"""
        return self._store
