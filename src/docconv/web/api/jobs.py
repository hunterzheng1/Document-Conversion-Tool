"""Job 相关 API 端点。"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse

from docconv.service import ConversionJobService
from docconv.service.job_models import (
    ConversionRequest,
    normalize_web_request,
)

from .schemas import (
    APIResponse,
    JobCreateResponse,
    JobStatusResponse,
    JobListItem,
    ProgressInfo,
    ApiErrorCodes,
)
from .dependencies import get_job_service, get_server_config, verify_auth_token
from .validation import (
    validate_file_extension,
    validate_file_size,
    validate_dpi,
    validate_concurrency,
    validate_instruction,
    validate_model_profile,
    ValidationError as AppValidationError,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/jobs",
    tags=["jobs"],
    dependencies=[Depends(verify_auth_token)],
)


# ---------------------------------------------------------------------------
# POST /api/v1/jobs/upload - 上传文件并创建任务
# ---------------------------------------------------------------------------

@router.post(
    "/upload",
    summary="上传 PDF 并创建转换任务",
    status_code=201,
)
async def create_job(
    file: Annotated[UploadFile, File(description="PDF 文件")],
    instruction: Annotated[str | None, Form(max_length=1000)] = None,
    model_profile: Annotated[str | None, Form()] = None,
    dpi: Annotated[int | None, Form()] = None,
    concurrency: Annotated[int | None, Form()] = None,
    dry_run: Annotated[bool, Form()] = False,
    no_cache: Annotated[bool, Form()] = False,
    sensitive: Annotated[bool, Form()] = False,
    job_service: ConversionJobService = Depends(get_job_service),
    server_config: dict = Depends(get_server_config),
) -> APIResponse[JobCreateResponse]:
    """接收 PDF 文件上传，创建 queued 状态的转换任务。

    文件流式写入临时目录，然后调用 ConversionJobService.create_job。
    """
    # 1. 获取上传配置
    upload_config = server_config.get("upload", {})
    max_size_mb = int(upload_config.get("max_file_size_mb", 100))

    # 2. 校验文件名和扩展名
    filename = file.filename or "unknown.pdf"
    validate_file_extension(filename)

    # 3. 校验文件大小（如果已知）
    if file.size is not None:
        validate_file_size(file.size, max_size_mb)

    # 4. 校验可选参数
    validate_dpi(dpi)
    validate_concurrency(concurrency)
    validate_instruction(instruction)
    validate_model_profile(model_profile)

    # 5. 流式写入临时文件
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".pdf", prefix="upload_")
    try:
        total_bytes = 0
        max_bytes = max_size_mb * 1024 * 1024

        with os.fdopen(tmp_fd, "wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)  # 1MB chunks
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise AppValidationError(
                        ApiErrorCodes.FILE_TOO_LARGE,
                        f"文件大小超过限制 {max_size_mb} MB",
                    )
                f.write(chunk)

        # 6. 构建转换请求
        request = ConversionRequest(
            source="web",
            input_file_path=tmp_path,
            original_filename=filename,
            instruction=instruction or "",
            options={
                k: v for k, v in {
                    "model": model_profile,
                    "dpi": dpi,
                    "parallel": concurrency,
                    "sensitive_mode": sensitive,
                }.items()
                if v is not None and v is not False
            },
        )

        # 7. 创建 job
        result = job_service.create_job(request)

        return APIResponse.success(
            data=JobCreateResponse(
                job_id=result["job_id"],
                status=result["status"],
                progress=ProgressInfo(
                    total_pages=0,
                    completed_pages=0,
                    failed_pages=0,
                    stage="queued",
                ),
            ),
        )

    except AppValidationError:
        raise
    except Exception:
        # 确保临时文件被清理
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


# ---------------------------------------------------------------------------
# GET /api/v1/jobs - 任务列表
# ---------------------------------------------------------------------------

@router.get(
    "",
    summary="查询任务列表",
)
async def list_jobs(
    status: str | None = None,
    limit: int = 50,
    job_service: ConversionJobService = Depends(get_job_service),
) -> APIResponse[list[JobListItem]]:
    """查询任务列表，支持按状态过滤。"""
    from docconv.service.job_models import JobStatus

    # 限制 limit 上限
    limit = min(limit, 200)

    # 查询指定状态的任务
    target_status = status if status else JobStatus.QUEUED
    try:
        records = job_service.store.list_by_status(target_status, limit=limit)
    except Exception as exc:
        logger.error(f"查询任务列表失败: {exc}")
        raise HTTPException(status_code=500, detail="查询任务列表失败")

    items = []
    for record in records:
        progress = record.progress_json or {}
        items.append(JobListItem(
            job_id=record.job_id,
            status=record.status,
            original_filename=record.original_filename or "",
            source=record.source,
            created_at=record.created_at,
            progress=ProgressInfo(
                total_pages=progress.get("total_pages", 0),
                completed_pages=progress.get("completed_pages", 0),
                failed_pages=progress.get("failed_pages", 0),
                stage=record.status,
            ),
        ))

    return APIResponse.success(data=items)


# ---------------------------------------------------------------------------
# GET /api/v1/jobs/{job_id} - 查询任务状态
# ---------------------------------------------------------------------------

@router.get(
    "/{job_id}",
    summary="查询任务状态",
)
async def get_job_status(
    job_id: str,
    job_service: ConversionJobService = Depends(get_job_service),
) -> APIResponse[JobStatusResponse]:
    """查询指定任务的状态和进度。

    不暴露服务器文件系统内部路径，仅返回安全信息。
    """
    record = job_service.get_job(job_id)

    progress = record.progress_json or {}

    data = JobStatusResponse(
        job_id=record.job_id,
        status=record.status,
        original_filename=record.original_filename or "",
        source=record.source,
        instruction=record.instruction or "",
        created_at=record.created_at,
        updated_at=record.updated_at,
        expires_at=record.expires_at,
        progress=ProgressInfo(
            total_pages=progress.get("total_pages", 0),
            completed_pages=progress.get("completed_pages", 0),
            failed_pages=progress.get("failed_pages", 0),
            stage=record.status,
        ),
        error_type=record.error_type or "",
        error_message=record.error_message or "",
    )

    return APIResponse.success(data=data)


# ---------------------------------------------------------------------------
# GET /api/v1/jobs/{job_id}/result - 下载转换结果
# ---------------------------------------------------------------------------

@router.get(
    "/{job_id}/result",
    summary="下载 Markdown 结果文件",
)
async def download_result(
    job_id: str,
    job_service: ConversionJobService = Depends(get_job_service),
) -> FileResponse:
    """下载已完成任务的 Markdown 结果文件。

    仅当 job 状态为 succeeded 且 result.md 存在时可用。
    路径由 JobService 内部管理，不接受用户传入。
    """
    record = job_service.get_job(job_id)

    if record.status != "succeeded":
        from docconv.service.job_models import ServiceError, ErrorCodes
        raise ServiceError(
            ErrorCodes.SVC2002,
            f"任务状态为 '{record.status}'，结果文件不可用",
        )

    result_path = record.output_path
    if not result_path or not Path(result_path).exists():
        from docconv.service.job_models import ServiceError, ErrorCodes
        raise ServiceError(
            ErrorCodes.SVC2001,
            "结果文件不存在",
        )

    return FileResponse(
        path=result_path,
        media_type="text/markdown",
        filename=f"{job_id}_result.md",
    )


# ---------------------------------------------------------------------------
# GET /api/v1/jobs/{job_id}/report - 下载转换报告
# ---------------------------------------------------------------------------

@router.get(
    "/{job_id}/report",
    summary="下载转换报告文件",
)
async def download_report(
    job_id: str,
    job_service: ConversionJobService = Depends(get_job_service),
) -> FileResponse:
    """下载任务的转换报告文件。

    当 job 状态为 failed 或 succeeded 时均可下载。
    """
    record = job_service.get_job(job_id)

    report_path = record.report_path
    if not report_path or not Path(report_path).exists():
        from docconv.service.job_models import ServiceError, ErrorCodes
        raise ServiceError(
            ErrorCodes.SVC2001,
            "报告文件不存在",
        )

    return FileResponse(
        path=report_path,
        media_type="text/markdown",
        filename=f"{job_id}_report.md",
    )


# ---------------------------------------------------------------------------
# POST /api/v1/jobs/{job_id}/cancel - 取消任务
# ---------------------------------------------------------------------------

@router.post(
    "/{job_id}/cancel",
    summary="取消任务",
)
async def cancel_job(
    job_id: str,
    job_service: ConversionJobService = Depends(get_job_service),
) -> APIResponse[dict]:
    """取消 queued 或 running 状态的任务。"""
    result = job_service.cancel_job(job_id)
    return APIResponse.success(data=result)
