"""健康检查端点。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from docconv.service import ConversionJobService

from .schemas import APIResponse, HealthResponse
from .dependencies import get_job_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    summary="健康检查",
    description="返回 API 服务状态、job store 可用性。",
)
async def health_check(
    job_service: ConversionJobService = Depends(get_job_service),
) -> APIResponse[HealthResponse]:
    """健康检查端点。

    检查 job store 连接是否正常，返回服务整体状态。
    """
    job_store_status = "ok"
    overall_status = "ok"

    try:
        # 通过 count_by_status 探测 SQLite 连接是否可用
        job_service.store.count_by_status("queued")
    except Exception as exc:
        logger.warning(f"job store 不可用: {exc}")
        job_store_status = "error"
        overall_status = "degraded"

    data = HealthResponse(
        status=overall_status,
        job_store=job_store_status,
        version="1.0.0",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    return APIResponse.success(data=data)
