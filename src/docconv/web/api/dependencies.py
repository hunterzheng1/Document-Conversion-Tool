"""FastAPI 依赖注入函数。"""

from __future__ import annotations

from typing import Any

from fastapi import Request

from docconv.service import ConversionJobService


# ---------------------------------------------------------------------------
# Service 依赖
# ---------------------------------------------------------------------------

def get_job_service(request: Request) -> ConversionJobService:
    """从 app.state 获取 ConversionJobService 实例。"""
    return request.app.state.job_service


# ---------------------------------------------------------------------------
# 配置依赖
# ---------------------------------------------------------------------------

def get_server_config(request: Request) -> dict[str, Any]:
    """从 app.state 获取 server 配置。"""
    return request.app.state.server_config


# ---------------------------------------------------------------------------
# 认证依赖（可选启用）
# ---------------------------------------------------------------------------

# 默认不启用认证
_AUTH_ENABLED = False
_AUTH_TOKEN: str | None = None


def configure_auth(enabled: bool, token: str | None = None) -> None:
    """配置认证参数。

    Args:
        enabled: 是否启用认证
        token: 访问令牌
    """
    global _AUTH_ENABLED, _AUTH_TOKEN
    _AUTH_ENABLED = enabled
    _AUTH_TOKEN = token


async def verify_auth_token(request: Request) -> None:
    """验证请求的访问令牌。

    仅在认证启用时检查 Authorization: Bearer <token> header。
    认证未启用时直接放行。

    Raises:
        由异常处理器转换为 3001 错误
    """
    if not _AUTH_ENABLED:
        return

    from .schemas import ApiErrorCodes
    from .validation import ValidationError

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise ValidationError(
            ApiErrorCodes.UNAUTHORIZED, "缺少认证令牌"
        )

    token = auth_header[7:].strip()
    if not token or token != _AUTH_TOKEN:
        raise ValidationError(
            ApiErrorCodes.UNAUTHORIZED, "认证令牌无效"
        )
