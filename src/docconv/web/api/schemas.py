"""Pydantic 请求/响应 Schema 定义。"""

from __future__ import annotations

from enum import Enum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# API 响应结构
# ---------------------------------------------------------------------------

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    """统一 API 响应结构。

    所有端点返回相同的 JSON 结构，包含业务错误码、
    消息提示和实际数据。
    """

    code: int = Field(default=0, description="业务错误码，0 表示成功")
    msg: str = Field(default="success", description="提示信息")
    data: T | None = Field(default=None, description="响应数据")

    @classmethod
    def success(cls, data: T | None = None, msg: str = "success") -> "APIResponse[T]":
        """构建成功响应。"""
        return cls(code=0, msg=msg, data=data)

    @classmethod
    def error(cls, code: int, msg: str, data: Any | None = None) -> "APIResponse[Any]":
        """构建错误响应。"""
        return cls(code=code, msg=msg, data=data)

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        return self.model_dump(mode="json")


# ---------------------------------------------------------------------------
# 业务错误码（与 spec.md 一致）
# ---------------------------------------------------------------------------

class ApiErrorCodes:
    """Web API 业务错误码。"""

    UNSUPPORTED_FILE_TYPE = 1001  # 文件类型不支持
    FILE_TOO_LARGE = 1002  # 文件过大
    INVALID_PARAMETER = 1003  # 参数无效
    JOB_NOT_FOUND = 2001  # 任务不存在
    JOB_INVALID_STATE = 2002  # 任务状态不允许
    UNAUTHORIZED = 3001  # 未授权
    INTERNAL_ERROR = 5001  # 服务内部错误


# ---------------------------------------------------------------------------
# ServiceError -> API 错误码映射
# ---------------------------------------------------------------------------

def map_service_error_code(service_code: str) -> int:
    """将 service 层错误码映射为 API 业务错误码。

    Args:
        service_code: service 层错误码 (如 SVC1001)

    Returns:
        对应的 API 业务错误码
    """
    mapping = {
        "SVC1001": ApiErrorCodes.INVALID_PARAMETER,
        "SVC1002": ApiErrorCodes.INVALID_PARAMETER,
        "SVC2001": ApiErrorCodes.JOB_NOT_FOUND,
        "SVC2002": ApiErrorCodes.JOB_INVALID_STATE,
        "SVC5001": ApiErrorCodes.INTERNAL_ERROR,
    }
    return mapping.get(service_code, ApiErrorCodes.INTERNAL_ERROR)


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------

class ModelProfile(str, Enum):
    """模型档位。"""

    AUTO = "auto"
    PRIMARY = "primary"
    ECONOMY = "economy"
    FALLBACK = "fallback"


class JobStatusEnum(str, Enum):
    """Job 状态。"""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    """健康检查响应。"""

    status: str = Field(description="服务状态：ok / degraded")
    job_store: str = Field(description="Job store 状态：ok / error")
    version: str = Field(default="1.0.0", description="应用版本")
    timestamp: str = Field(description="ISO 8601 时间戳")


class ProgressInfo(BaseModel):
    """任务进度信息。"""

    total_pages: int = Field(default=0, ge=0, description="总页数")
    completed_pages: int = Field(default=0, ge=0, description="已完成页数")
    failed_pages: int = Field(default=0, ge=0, description="失败页数")
    stage: str = Field(default="queued", description="当前阶段")


class JobListItem(BaseModel):
    """任务列表项。"""

    job_id: str = Field(description="任务 ID")
    status: str = Field(description="任务状态")
    original_filename: str = Field(description="原始文件名")
    source: str = Field(description="来源（web/cli/bot）")
    created_at: str = Field(description="创建时间 (ISO 8601)")
    progress: ProgressInfo = Field(description="进度信息")


class JobStatusResponse(BaseModel):
    """任务状态查询响应。"""

    job_id: str = Field(description="任务 ID")
    status: str = Field(description="任务状态")
    original_filename: str = Field(description="原始文件名")
    source: str = Field(description="来源")
    instruction: str = Field(default="", description="转换指令")
    created_at: str = Field(description="创建时间")
    updated_at: str = Field(description="最后更新时间")
    expires_at: str = Field(description="过期时间")
    progress: ProgressInfo = Field(description="进度信息")
    error_type: str = Field(default="", description="错误类型")
    error_message: str = Field(default="", description="错误信息")


class JobCreateResponse(BaseModel):
    """任务创建响应。"""

    job_id: str = Field(description="任务 ID")
    status: str = Field(default="queued", description="任务状态")
    progress: ProgressInfo = Field(
        default_factory=lambda: ProgressInfo(
            total_pages=0, completed_pages=0,
            failed_pages=0, stage="queued",
        ),
        description="初始进度",
    )


class ModelProfileItem(BaseModel):
    """模型配置项。"""

    name: str = Field(description="模型名称")
    profile: str = Field(description="模型档位")
    provider: str = Field(description="提供者")
    available: bool = Field(default=True, description="是否可用")


class ModelListResponse(BaseModel):
    """模型列表响应。"""

    profiles: list[ModelProfileItem] = Field(
        default_factory=list,
        description="模型档位列表",
    )


class ErrorResponse(BaseModel):
    """错误响应详情。"""

    code: int = Field(description="业务错误码")
    msg: str = Field(description="错误描述")
    detail: str | None = Field(default=None, description="详细错误信息")
