"""错误处理中间件与请求 ID 注入。"""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError

from docconv.service.job_models import ServiceError

from .schemas import APIResponse, ApiErrorCodes, map_service_error_code
from .validation import ValidationError as AppValidationError

logger = logging.getLogger(__name__)

# 请求 ID HTTP Header 名称
REQUEST_ID_HEADER = "X-Request-ID"


def setup_middleware(app: FastAPI) -> None:
    """注册全局中间件和异常处理器。

    Args:
        app: FastAPI 应用实例
    """
    # 请求 ID 中间件
    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        request_id = request.headers.get(REQUEST_ID_HEADER)
        if not request_id:
            request_id = uuid.uuid4().hex[:16]

        # 将 request_id 存入 request.state，供下游使用
        request.state.request_id = request_id

        start_time = time.time()
        response = await call_next(request)
        elapsed = time.time() - start_time

        # 在响应头中附加 request_id
        response.headers[REQUEST_ID_HEADER] = request_id

        # 记录请求日志
        logger.info(
            f"request_id={request_id} method={request.method} "
            f"path={request.url.path} status={response.status_code} "
            f"elapsed={elapsed:.3f}s"
        )

        return response

    # ---- 异常处理器 ----

    # ServiceError -> 对应 HTTP 状态码
    @app.exception_handler(ServiceError)
    async def handle_service_error(request: Request, exc: ServiceError):
        api_code = map_service_error_code(exc.code)

        # 根据错误码确定 HTTP 状态码
        http_status = _api_code_to_http_status(api_code)

        return JSONResponse(
            status_code=http_status,
            content=APIResponse.error(code=api_code, msg=exc.message).to_dict(),
        )

    # 自定义校验错误
    @app.exception_handler(AppValidationError)
    async def handle_app_validation_error(
        request: Request, exc: AppValidationError
    ):
        return JSONResponse(
            status_code=400,
            content=APIResponse.error(
                code=exc.code, msg=exc.message
            ).to_dict(),
        )

    # Pydantic 校验错误
    @app.exception_handler(PydanticValidationError)
    async def handle_pydantic_error(
        request: Request, exc: PydanticValidationError
    ):
        errors = exc.errors()
        detail = "; ".join(
            f"{'.'.join(str(l) for l in e['loc'])}: {e['msg']}"
            for e in errors
        )
        return JSONResponse(
            status_code=400,
            content=APIResponse.error(
                code=ApiErrorCodes.INVALID_PARAMETER,
                msg=f"参数校验失败: {detail}",
            ).to_dict(),
        )

    # 通用未捕获异常
    @app.exception_handler(Exception)
    async def handle_generic_error(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", "unknown")
        logger.error(
            f"request_id={request_id} unhandled_error: {exc}",
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content=APIResponse.error(
                code=ApiErrorCodes.INTERNAL_ERROR,
                msg="服务内部错误，请稍后重试",
            ).to_dict(),
        )


def _api_code_to_http_status(api_code: int) -> int:
    """将 API 业务错误码映射为 HTTP 状态码。

    Args:
        api_code: API 业务错误码

    Returns:
        对应的 HTTP 状态码
    """
    mapping = {
        ApiErrorCodes.UNSUPPORTED_FILE_TYPE: 400,
        ApiErrorCodes.FILE_TOO_LARGE: 400,
        ApiErrorCodes.INVALID_PARAMETER: 400,
        ApiErrorCodes.JOB_NOT_FOUND: 404,
        ApiErrorCodes.JOB_INVALID_STATE: 409,
        ApiErrorCodes.UNAUTHORIZED: 401,
        ApiErrorCodes.INTERNAL_ERROR: 500,
    }
    return mapping.get(api_code, 500)
