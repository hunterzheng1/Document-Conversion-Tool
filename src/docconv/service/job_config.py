"""Job 配置项和默认值。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from typing import Any


# ---------------------------------------------------------------------------
# 默认配置
# ---------------------------------------------------------------------------

_DEFAULTS: dict[str, Any] = {
    "storage_root": ".data/docconv",
    "retention_hours": 24,
    "max_running_jobs": 1,
    "max_queued_jobs": 20,
    "worker_poll_interval_seconds": 2,
    "enabled": True,
    "recover_running_on_start": True,
    "cleanup_expired": True,
    "recover_timeout_seconds": 600,
    "heartbeat_interval_seconds": 30,
}


# ---------------------------------------------------------------------------
# JobConfig 数据类
# ---------------------------------------------------------------------------

@dataclass
class JobConfig:
    """Job 服务配置，支持从环境变量和字典覆盖。"""

    storage_root: str = _DEFAULTS["storage_root"]
    retention_hours: int = _DEFAULTS["retention_hours"]
    max_running_jobs: int = _DEFAULTS["max_running_jobs"]
    max_queued_jobs: int = _DEFAULTS["max_queued_jobs"]
    worker_poll_interval_seconds: int = _DEFAULTS["worker_poll_interval_seconds"]
    enabled: bool = _DEFAULTS["enabled"]
    recover_running_on_start: bool = _DEFAULTS["recover_running_on_start"]
    cleanup_expired: bool = _DEFAULTS["cleanup_expired"]
    recover_timeout_seconds: int = _DEFAULTS["recover_timeout_seconds"]
    heartbeat_interval_seconds: int = _DEFAULTS["heartbeat_interval_seconds"]

    def __post_init__(self) -> None:
        """配置校验。"""
        if self.max_running_jobs < 1:
            raise ValueError(
                f"max_running_jobs 必须 >= 1，当前值: {self.max_running_jobs}"
            )
        if self.max_queued_jobs < 1:
            raise ValueError(
                f"max_queued_jobs 必须 >= 1，当前值: {self.max_queued_jobs}"
            )
        if not (1 <= self.worker_poll_interval_seconds <= 5):
            raise ValueError(
                f"worker_poll_interval_seconds 必须在 1-5 秒之间，"
                f"当前值: {self.worker_poll_interval_seconds}"
            )
        if self.retention_hours < 1:
            raise ValueError(
                f"retention_hours 必须 >= 1，当前值: {self.retention_hours}"
            )
        if self.recover_timeout_seconds < 60:
            raise ValueError(
                f"recover_timeout_seconds 必须 >= 60，"
                f"当前值: {self.recover_timeout_seconds}"
            )
        if not (10 <= self.heartbeat_interval_seconds <= 120):
            raise ValueError(
                f"heartbeat_interval_seconds 必须在 10-120 秒之间，"
                f"当前值: {self.heartbeat_interval_seconds}"
            )

    @classmethod
    def from_dict(cls, overrides: dict[str, Any] | None = None) -> "JobConfig":
        """从字典覆盖创建配置。

        Args:
            overrides: 要覆盖的键值对

        Returns:
            JobConfig 实例
        """
        data = {**_DEFAULTS}
        if overrides:
            data.update(overrides)
        return cls(**data)

    @classmethod
    def from_env(cls, overrides: dict[str, Any] | None = None) -> "JobConfig":
        """从环境变量覆盖创建配置。

        支持的环境变量：
        - DOC_CONV_STORAGE_ROOT
        - DOC_CONV_RETENTION_HOURS
        - DOC_CONV_MAX_RUNNING_JOBS
        - DOC_CONV_MAX_QUEUED_JOBS
        - DOC_CONV_POLL_INTERVAL
        - DOC_CONV_ENABLED
        - DOC_CONV_RECOVER_ON_START
        - DOC_CONV_RECOVER_TIMEOUT
        - DOC_CONV_HEARTBEAT_INTERVAL

        Args:
            overrides: 额外的覆盖字典（优先级高于环境变量）

        Returns:
            JobConfig 实例
        """
        data = {**_DEFAULTS}

        env_map = {
            "DOCCONV_STORAGE_ROOT": ("storage_root", str),
            "DOCCONV_RETENTION_HOURS": ("retention_hours", int),
            "DOCCONV_MAX_RUNNING_JOBS": ("max_running_jobs", int),
            "DOCCONV_MAX_QUEUED_JOBS": ("max_queued_jobs", int),
            "DOCCONV_POLL_INTERVAL": ("worker_poll_interval_seconds", int),
            "DOCCONV_ENABLED": ("enabled", lambda v: v.lower() in ("true", "1", "yes")),
            "DOCCONV_RECOVER_ON_START": ("recover_running_on_start", lambda v: v.lower() in ("true", "1", "yes")),
            "DOCCONV_CLEANUP_EXPIRED": ("cleanup_expired", lambda v: v.lower() in ("true", "1", "yes")),
            "DOCCONV_RECOVER_TIMEOUT": ("recover_timeout_seconds", int),
            "DOCCONV_HEARTBEAT_INTERVAL": ("heartbeat_interval_seconds", int),
        }

        for env_var, (key, converter) in env_map.items():
            value = os.environ.get(env_var)
            if value is not None:
                try:
                    data[key] = converter(value)
                except (ValueError, TypeError):
                    pass  # 忽略非法值，保持默认

        if overrides:
            data.update(overrides)

        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        return asdict(self)
