"""Job 数据模型：状态枚举、记录定义、请求模型、错误码。"""

from __future__ import annotations

import os
import uuid
import json
import shutil
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# 错误码常量
# ---------------------------------------------------------------------------

class ErrorCodes:
    """Job 服务错误码。"""
    SVC1001 = "SVC1001"  # 无效参数
    SVC1002 = "SVC1002"  # 队列溢出
    SVC2001 = "SVC2001"  # Job 不存在
    SVC2002 = "SVC2002"  # 非法状态转换
    SVC2003 = "SVC2003"  # 队列已满，拒绝新任务
    SVC5001 = "SVC5001"  # 内部错误


# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------

class ServiceError(Exception):
    """Job 服务异常。"""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


# ---------------------------------------------------------------------------
# JobStatus 枚举 & 状态机
# ---------------------------------------------------------------------------

class JobStatus:
    """Job 状态枚举与状态转换规则。"""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"

    # 合法状态转换映射表
    # key: 源状态, value: 允许的目标状态集合
    ALLOWED_TRANSITIONS: dict[str, set[str]] = {
        QUEUED:    {RUNNING, CANCELLED},
        RUNNING:   {SUCCEEDED, FAILED, CANCELLED},
        SUCCEEDED: {EXPIRED},
        FAILED:    {EXPIRED},
        CANCELLED: {EXPIRED},
        EXPIRED:   set(),  # 终态，不再转换
    }

    @classmethod
    def can_transition(cls, from_status: str, to_status: str) -> bool:
        """验证状态转换是否合法。

        Args:
            from_status: 当前状态
            to_status: 目标状态

        Returns:
            是否允许该转换

        Raises:
            ValueError: 任一状态不是合法的 JobStatus 值
        """
        valid_statuses = {
            cls.QUEUED, cls.RUNNING, cls.SUCCEEDED,
            cls.FAILED, cls.CANCELLED, cls.EXPIRED,
        }
        if from_status not in valid_statuses:
            raise ValueError(f"非法的源状态: {from_status}")
        if to_status not in valid_statuses:
            raise ValueError(f"非法的目标状态: {to_status}")

        allowed = cls.ALLOWED_TRANSITIONS.get(from_status, set())
        return to_status in allowed


# ---------------------------------------------------------------------------
# JobRecord dataclass
# ---------------------------------------------------------------------------

@dataclass
class JobRecord:
    """Job 记录，映射 jobs 表全部字段。"""

    job_id: str = ""
    source: str = ""
    status: str = JobStatus.QUEUED
    original_filename: str = ""
    input_path: str = ""
    output_path: str = ""
    report_path: str = ""
    instruction: str = ""
    options_json: dict = field(default_factory=dict)
    progress_json: dict = field(default_factory=dict)
    error_type: str = ""
    error_message: str = ""
    locked_by: str = ""
    heartbeat_at: str = ""
    created_at: str = ""
    updated_at: str = ""
    expires_at: str = ""

    @staticmethod
    def generate_job_id() -> str:
        """生成 job_id，格式: job_YYYYMMDD_<随机字符串>。"""
        now = datetime.now(timezone.utc).strftime("%Y%m%d")
        uid = uuid.uuid4().hex[:8]
        return f"job_{now}_{uid}"

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JobRecord":
        """从字典反序列化。"""
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)

    def copy_with(self, **overrides: Any) -> "JobRecord":
        """返回一个新 JobRecord，仅覆盖指定字段。"""
        current = self.to_dict()
        current.update(overrides)
        return self.__class__.from_dict(current)


# ---------------------------------------------------------------------------
# ConversionRequest 统一请求模型
# ---------------------------------------------------------------------------

# options 白名单字段（仅允许这些键出现在 options 中）
OPTIONS_WHITELIST = {
    "parallel", "verbose", "sensitive_mode", "resume",
    "model", "temperature", "max_tokens",
}

INSTRUCTION_MAX_LENGTH = 1000


@dataclass
class ConversionRequest:
    """统一转换请求，所有入口（Web/CLI/Telegram/Feishu）的契约。"""

    source: str = ""
    input_file_path: str = ""
    original_filename: str = ""
    instruction: str = ""
    options: dict = field(default_factory=dict)

    def validate(self) -> None:
        """校验请求参数。

        校验规则：
        1. source 不能为空
        2. input_file_path 不能为空且文件必须存在
        3. instruction 长度 <= 1000 字符
        4. options 仅包含白名单字段

        Raises:
            ServiceError: 校验失败时抛出，code=SVC1001
        """
        if not self.source:
            raise ServiceError(
                ErrorCodes.SVC1001, "source 不能为空"
            )
        if not self.input_file_path:
            raise ServiceError(
                ErrorCodes.SVC1001, "input_file_path 不能为空"
            )
        if not os.path.exists(self.input_file_path):
            raise ServiceError(
                ErrorCodes.SVC1001,
                f"输入文件不存在: {self.input_file_path}",
            )
        if len(self.instruction) > INSTRUCTION_MAX_LENGTH:
            raise ServiceError(
                ErrorCodes.SVC1001,
                f"instruction 长度超过 {INSTRUCTION_MAX_LENGTH} 字符",
            )

        # 校验 options 白名单
        if self.options:
            extra_keys = set(self.options.keys()) - OPTIONS_WHITELIST
            if extra_keys:
                raise ServiceError(
                    ErrorCodes.SVC1001,
                    f"options 包含非法字段: {', '.join(sorted(extra_keys))}",
                )


# ---------------------------------------------------------------------------
# 请求规范化函数
# ---------------------------------------------------------------------------

def normalize_web_request(
    file_path: str,
    filename: str,
    options: dict | None = None,
) -> ConversionRequest:
    """规范化 Web 入口请求。

    Args:
        file_path: 已接收文件路径
        filename: 原始文件名
        options: 转换参数

    Returns:
        校验通过的 ConversionRequest
    """
    req = ConversionRequest(
        source="web",
        input_file_path=file_path,
        original_filename=filename,
        options=options or {},
    )
    req.validate()
    return req


def normalize_bot_request(
    file_path: str,
    filename: str,
    instruction: str = "",
    platform: str = "telegram",
    platform_meta: dict | None = None,
    options: dict | None = None,
) -> ConversionRequest:
    """规范化 Bot 入口请求（Telegram / Feishu）。

    Args:
        file_path: 已接收文件路径
        filename: 原始文件名
        instruction: 用户指令
        platform: 平台标识 (telegram / feishu)
        platform_meta: 平台关联元数据
        options: 转换参数

    Returns:
        校验通过的 ConversionRequest
    """
    req = ConversionRequest(
        source=platform,
        input_file_path=file_path,
        original_filename=filename,
        instruction=instruction,
        options=options or {},
    )
    req.validate()
    return req


def normalize_cli_request(
    file_path: str,
    filename: str,
    options: dict | None = None,
) -> ConversionRequest:
    """规范化 CLI 入口请求。

    Args:
        file_path: 输入文件路径
        filename: 原始文件名
        options: 转换参数

    Returns:
        校验通过的 ConversionRequest
    """
    req = ConversionRequest(
        source="cli",
        input_file_path=file_path,
        original_filename=filename,
        options=options or {},
    )
    req.validate()
    return req
