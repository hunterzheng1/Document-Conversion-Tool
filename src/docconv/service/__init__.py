"""Service 模块：任务管理、工作区、Job 存储与编排。"""

from __future__ import annotations

from .job_models import (
    JobStatus,
    JobRecord,
    ConversionRequest,
    ServiceError,
)
from .job_store import SQLiteJobStore
from .workspace import JobWorkspace
from .conversion_job_service import ConversionJobService
from .state_repo import SQLiteStateRepository

__all__ = [
    "JobStatus",
    "JobRecord",
    "ConversionRequest",
    "ServiceError",
    "SQLiteJobStore",
    "JobWorkspace",
    "ConversionJobService",
    "SQLiteStateRepository",
]
