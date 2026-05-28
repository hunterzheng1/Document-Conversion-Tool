"""Schema 和 API 响应结构单元测试 (TASK-WA-18)。"""

from __future__ import annotations

import json

import pytest

from docconv.web.api.schemas import (
    APIResponse,
    ApiErrorCodes,
    ModelProfile,
    JobStatusEnum,
    ProgressInfo,
    JobCreateResponse,
    JobStatusResponse,
    HealthResponse,
    ModelProfileItem,
    ModelListResponse,
    ErrorResponse,
    map_service_error_code,
)


# ===================================================================
# ModelProfile 枚举测试
# ===================================================================

class TestModelProfile:
    """ModelProfile 枚举测试。"""

    def test_all_profiles_exist(self):
        """所有设计档位都存在。"""
        values = {m.value for m in ModelProfile}
        assert values == {"auto", "primary", "economy", "fallback"}

    def test_auto_profile(self):
        assert ModelProfile.AUTO.value == "auto"

    def test_invalid_profile_raises(self):
        with pytest.raises(ValueError):
            ModelProfile("invalid")


# ===================================================================
# JobStatusEnum 枚举测试
# ===================================================================

class TestJobStatusEnum:
    """JobStatusEnum 枚举测试。"""

    def test_all_statuses_exist(self):
        values = {s.value for s in JobStatusEnum}
        assert values == {"queued", "running", "succeeded", "failed", "cancelled", "expired"}


# ===================================================================
# ProgressInfo 测试
# ===================================================================

class TestProgressInfo:
    """ProgressInfo 模型测试。"""

    def test_default_values(self):
        p = ProgressInfo()
        assert p.total_pages == 0
        assert p.completed_pages == 0
        assert p.failed_pages == 0
        assert p.stage == "queued"

    def test_custom_values(self):
        p = ProgressInfo(total_pages=10, completed_pages=5, failed_pages=1, stage="running")
        assert p.total_pages == 10
        assert p.completed_pages == 5
        assert p.failed_pages == 1
        assert p.stage == "running"


# ===================================================================
# APIResponse 泛型响应测试
# ===================================================================

class TestAPIResponse:
    """APIResponse 泛型响应模型测试。"""

    def test_default_success(self):
        r = APIResponse()
        assert r.code == 0
        assert r.msg == "success"
        assert r.data is None

    def test_success_with_data(self):
        r = APIResponse.success(data={"key": "value"})
        assert r.code == 0
        assert r.msg == "success"
        assert r.data == {"key": "value"}

    def test_success_custom_msg(self):
        r = APIResponse.success(data=None, msg="created")
        assert r.code == 0
        assert r.msg == "created"

    def test_error_response(self):
        r = APIResponse.error(code=1001, msg="文件类型不支持")
        assert r.code == 1001
        assert r.msg == "文件类型不支持"
        assert r.data is None

    def test_error_with_detail_data(self):
        r = APIResponse.error(code=2001, msg="任务不存在", data={"job_id": "123"})
        assert r.code == 2001
        assert r.data == {"job_id": "123"}

    def test_serialization(self):
        r = APIResponse.success(data={"job_id": "abc", "status": "queued"})
        d = r.to_dict()
        assert d["code"] == 0
        assert d["msg"] == "success"
        assert d["data"]["job_id"] == "abc"

    def test_serialization_with_nested_model(self):
        progress = ProgressInfo(total_pages=5, completed_pages=2, failed_pages=0, stage="running")
        job_resp = JobCreateResponse(job_id="job_123", status="running", progress=progress)
        r = APIResponse.success(data=job_resp)
        d = r.to_dict()
        assert d["data"]["job_id"] == "job_123"
        assert d["data"]["progress"]["total_pages"] == 5


# ===================================================================
# JobCreateResponse 测试
# ===================================================================

class TestJobCreateResponse:
    """JobCreateResponse 模型测试。"""

    def test_default_progress(self):
        r = JobCreateResponse(job_id="job_123")
        assert r.job_id == "job_123"
        assert r.status == "queued"
        assert r.progress.total_pages == 0
        assert r.progress.stage == "queued"


# ===================================================================
# HealthResponse 测试
# ===================================================================

class TestHealthResponse:
    """HealthResponse 模型测试。"""

    def test_serialization(self):
        r = HealthResponse(status="ok", job_store="ok", timestamp="2026-01-01T00:00:00Z")
        d = r.model_dump()
        assert d["status"] == "ok"
        assert d["job_store"] == "ok"
        assert d["version"] == "1.0.0"


# ===================================================================
# ApiErrorCodes 常量测试
# ===================================================================

class TestApiErrorCodes:
    """API 错误码常量测试。"""

    def test_error_code_values(self):
        """所有错误码与 spec.md 一致。"""
        assert ApiErrorCodes.UNSUPPORTED_FILE_TYPE == 1001
        assert ApiErrorCodes.FILE_TOO_LARGE == 1002
        assert ApiErrorCodes.INVALID_PARAMETER == 1003
        assert ApiErrorCodes.JOB_NOT_FOUND == 2001
        assert ApiErrorCodes.JOB_INVALID_STATE == 2002
        assert ApiErrorCodes.UNAUTHORIZED == 3001
        assert ApiErrorCodes.INTERNAL_ERROR == 5001


# ===================================================================
# map_service_error_code 测试
# ===================================================================

class TestMapServiceErrorCode:
    """service -> API 错误码映射测试。"""

    def test_svc1001_maps_to_1003(self):
        assert map_service_error_code("SVC1001") == ApiErrorCodes.INVALID_PARAMETER

    def test_svc2001_maps_to_2001(self):
        assert map_service_error_code("SVC2001") == ApiErrorCodes.JOB_NOT_FOUND

    def test_svc2002_maps_to_2002(self):
        assert map_service_error_code("SVC2002") == ApiErrorCodes.JOB_INVALID_STATE

    def test_svc5001_maps_to_5001(self):
        assert map_service_error_code("SVC5001") == ApiErrorCodes.INTERNAL_ERROR

    def test_unknown_maps_to_5001(self):
        assert map_service_error_code("UNKNOWN") == ApiErrorCodes.INTERNAL_ERROR


# ===================================================================
# ErrorResponse 测试
# ===================================================================

class TestErrorResponse:
    """ErrorResponse 模型测试。"""

    def test_with_optional_detail(self):
        e = ErrorResponse(code=1001, msg="不支持")
        assert e.detail is None

    def test_with_detail(self):
        e = ErrorResponse(code=1001, msg="不支持", detail="expected .pdf")
        assert e.detail == "expected .pdf"
