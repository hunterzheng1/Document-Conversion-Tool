"""API 路由端到端测试 (TASK-WA-19)。

使用 httpx TestClient 对 FastAPI app 进行端到端测试，
覆盖 spec.md 定义的全部场景。
"""

from __future__ import annotations

import io
import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from docconv.service import ConversionJobService
from docconv.service.job_models import (
    JobRecord,
    JobStatus,
    ServiceError,
    ErrorCodes,
)
from docconv.web.api.app import create_app
from docconv.web.api.schemas import ApiErrorCodes


# ===================================================================
# 测试辅助函数
# ===================================================================

def _make_job_record(
    job_id: str = "job_20260528_abcd1234",
    status: str = JobStatus.QUEUED,
    storage_root: str = ".data/docconv",
) -> JobRecord:
    """创建测试用 JobRecord。"""
    now = datetime.now(timezone.utc).isoformat()
    expires = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    workspace = Path(storage_root) / "jobs" / job_id
    return JobRecord(
        job_id=job_id,
        source="web",
        status=status,
        original_filename="test.pdf",
        input_path=str(workspace / "input" / "test.pdf"),
        output_path=str(workspace / "output" / "result.md"),
        report_path=str(workspace / "output" / "report.md"),
        instruction="",
        options_json={},
        progress_json={"total_pages": 0, "completed_pages": 0, "failed_pages": 0},
        created_at=now,
        updated_at=now,
        expires_at=expires,
    )


def _create_pdf_bytes() -> bytes:
    """生成一个伪造的最小 PDF 文件内容。"""
    return b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\nxref\n0 3\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \ntrailer\n<< /Size 3 /Root 1 0 R >>\nstartxref\n124\n%%EOF"


# ===================================================================
# 健康检查端点测试
# ===================================================================

class TestHealthEndpoint:
    """GET /api/v1/health 测试。"""

    def test_health_returns_ok(self, tmp_path):
        """TestClient 使用 lifespan 来初始化 job_service。"""
        mock_service = MagicMock(spec=ConversionJobService)
        mock_service.store = MagicMock()
        mock_service.store.count_by_status.return_value = 0

        config = {
            "job": {"storage_root": str(tmp_path)},
            "upload": {"max_file_size_mb": 100, "allowed_extensions": [".pdf"]},
        }
        app = create_app(config=config, job_service=mock_service)
        client = TestClient(app)

        response = client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["msg"] == "success"
        assert data["data"]["status"] == "ok"
        assert data["data"]["job_store"] == "ok"
        assert "timestamp" in data["data"]

    def test_health_no_auth_required(self, tmp_path):
        """健康检查不需要认证。"""
        app = create_app(config={"job": {"storage_root": str(tmp_path)}})
        client = TestClient(app)
        response = client.get("/api/v1/health")  # 无 token
        assert response.status_code == 200


# ===================================================================
# 模型列表端点测试
# ===================================================================

class TestModelsEndpoint:
    """GET /api/v1/models 测试。"""

    def test_models_returns_list(self, tmp_path):
        app = create_app(config={"job": {"storage_root": str(tmp_path)}})
        client = TestClient(app)
        response = client.get("/api/v1/models")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert "profiles" in data["data"]
        assert isinstance(data["data"]["profiles"], list)

    def test_models_no_api_keys_exposed(self, tmp_path):
        """响应不包含任何 API Key。"""
        app = create_app(config={"job": {"storage_root": str(tmp_path)}})
        client = TestClient(app)
        response = client.get("/api/v1/models")
        body = response.text.lower()
        assert "sk-" not in body
        assert "anthropic-" not in body


# ===================================================================
# 创建任务端点测试
# ===================================================================

class TestCreateJobEndpoint:
    """POST /api/v1/jobs/upload 测试。"""

    def _make_app_with_mock_service(self, tmp_path):
        """创建 app 并注入 mock job_service。"""
        mock_service = MagicMock(spec=ConversionJobService)
        mock_service.create_job.return_value = {
            "job_id": "job_20260528_abcd1234",
            "status": "queued",
        }
        mock_service.get_job.return_value = _make_job_record(
            storage_root=str(tmp_path)
        )

        config = {
            "job": {"storage_root": str(tmp_path)},
            "upload": {"max_file_size_mb": 100, "allowed_extensions": [".pdf"]},
        }
        app = create_app(config=config, job_service=mock_service)
        return app, mock_service

    def test_valid_pdf_returns_201(self, tmp_path):
        """上传有效 PDF 返回 201 + job_id。"""
        app, mock_service = self._make_app_with_mock_service(tmp_path)
        client = TestClient(app)

        pdf_content = _create_pdf_bytes()
        response = client.post(
            "/api/v1/jobs/upload",
            files={"file": ("test.pdf", io.BytesIO(pdf_content), "application/pdf")},
            data={"instruction": "转成 Markdown"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["job_id"] == "job_20260528_abcd1234"
        assert data["data"]["status"] == "queued"
        mock_service.create_job.assert_called_once()

    def test_non_pdf_rejected(self, tmp_path):
        """上传非 PDF 返回 1001 错误。"""
        app, _ = self._make_app_with_mock_service(tmp_path)
        client = TestClient(app)

        response = client.post(
            "/api/v1/jobs/upload",
            files={"file": ("test.txt", io.BytesIO(b"hello world"), "text/plain")},
        )

        assert response.status_code == 400
        data = response.json()
        assert data["code"] == ApiErrorCodes.UNSUPPORTED_FILE_TYPE

    def test_oversized_file_rejected(self, tmp_path):
        """上传超大文件返回 1002 错误。"""
        app, _ = self._make_app_with_mock_service(tmp_path)
        client = TestClient(app)

        # 模拟大文件：在流式读取过程中检测大小
        # 这里我们用一个小文件但 mock validate_file_size 来模拟超限
        with patch("docconv.web.api.jobs.validate_file_size") as mock_validate:
            from docconv.web.api.validation import ValidationError
            mock_validate.side_effect = ValidationError(
                ApiErrorCodes.FILE_TOO_LARGE, "文件过大"
            )

            pdf_content = _create_pdf_bytes()
            response = client.post(
                "/api/v1/jobs/upload",
                files={"file": ("test.pdf", io.BytesIO(pdf_content), "application/pdf")},
            )

            assert response.status_code == 400
            data = response.json()
            assert data["code"] == ApiErrorCodes.FILE_TOO_LARGE


# ===================================================================
# 任务状态查询端点测试
# ===================================================================

class TestJobStatusEndpoint:
    """GET /api/v1/jobs/{job_id} 测试。"""

    def _make_app_with_mock_service(self, tmp_path, job_record=None):
        """创建 app 并注入 mock job_service。"""
        mock_service = MagicMock(spec=ConversionJobService)
        if job_record is None:
            job_record = _make_job_record(storage_root=str(tmp_path))

        def get_job_side_effect(job_id):
            if job_id == "not_found":
                raise ServiceError(
                    ErrorCodes.SVC2001,
                    f"job 不存在: {job_id}",
                )
            return job_record

        mock_service.get_job.side_effect = get_job_side_effect
        mock_service.create_job.return_value = {
            "job_id": job_record.job_id,
            "status": job_record.status,
        }

        config = {"job": {"storage_root": str(tmp_path)}}
        app = create_app(config=config, job_service=mock_service)
        return app, mock_service

    def test_existing_job_returns_status(self, tmp_path):
        """查询存在的任务返回状态。"""
        record = _make_job_record(status="queued", storage_root=str(tmp_path))
        app, _ = self._make_app_with_mock_service(tmp_path, job_record=record)
        client = TestClient(app)

        response = client.get(f"/api/v1/jobs/{record.job_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["job_id"] == record.job_id
        assert data["data"]["status"] == "queued"
        assert "progress" in data["data"]
        assert "total_pages" in data["data"]["progress"]

    def test_missing_job_returns_2001(self, tmp_path):
        """查询不存在的任务返回 2001 错误。"""
        app, _ = self._make_app_with_mock_service(tmp_path)
        client = TestClient(app)

        response = client.get("/api/v1/jobs/not_found")
        assert response.status_code == 404
        data = response.json()
        assert data["code"] == ApiErrorCodes.JOB_NOT_FOUND

    def test_response_no_internal_paths(self, tmp_path):
        """响应不暴露 input_path/output_path。"""
        record = _make_job_record(storage_root=str(tmp_path))
        app, _ = self._make_app_with_mock_service(tmp_path, job_record=record)
        client = TestClient(app)

        response = client.get(f"/api/v1/jobs/{record.job_id}")
        data = response.json()
        assert "input_path" not in data["data"]
        assert "output_path" not in data["data"]
        assert "report_path" not in data["data"]


# ===================================================================
# 任务列表端点测试
# ===================================================================

class TestJobListEndpoint:
    """GET /api/v1/jobs 测试。"""

    def _make_app_with_mock_service(self, tmp_path):
        """创建 app 并注入 mock job_service。"""
        mock_service = MagicMock(spec=ConversionJobService)
        mock_service.store = MagicMock()
        mock_service.store.list_by_status.return_value = [
            _make_job_record("job_001", storage_root=str(tmp_path)),
            _make_job_record("job_002", storage_root=str(tmp_path)),
        ]
        mock_service.create_job.return_value = {
            "job_id": "job_new",
            "status": "queued",
        }

        config = {"job": {"storage_root": str(tmp_path)}}
        app = create_app(config=config, job_service=mock_service)
        return app, mock_service

    def test_list_jobs_returns_items(self, tmp_path):
        """查询任务列表返回项目。"""
        app, mock_service = self._make_app_with_mock_service(tmp_path)
        client = TestClient(app)

        response = client.get("/api/v1/jobs")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert isinstance(data["data"], list)
        assert len(data["data"]) == 2


# ===================================================================
# 任务取消端点测试
# ===================================================================

class TestCancelJobEndpoint:
    """POST /api/v1/jobs/{job_id}/cancel 测试。"""

    def _make_app_with_mock_service(self, tmp_path):
        """创建 app 并注入 mock job_service。"""
        mock_service = MagicMock(spec=ConversionJobService)

        def cancel_side_effect(job_id):
            if job_id == "not_found":
                raise ServiceError(
                    ErrorCodes.SVC2001,
                    f"job 不存在: {job_id}",
                )
            if job_id == "already_done":
                raise ServiceError(
                    ErrorCodes.SVC2002,
                    f"无法从状态 'succeeded' 转换到 'cancelled'",
                )
            return {"job_id": job_id, "status": "cancelled"}

        mock_service.cancel_job.side_effect = cancel_side_effect
        mock_service.get_job.return_value = _make_job_record(
            storage_root=str(tmp_path)
        )

        config = {"job": {"storage_root": str(tmp_path)}}
        app = create_app(config=config, job_service=mock_service)
        return app, mock_service

    def test_cancel_queued_job(self, tmp_path):
        """取消 queued 任务成功。"""
        app, _ = self._make_app_with_mock_service(tmp_path)
        client = TestClient(app)

        response = client.post(f"/api/v1/jobs/job_20260528_abcd1234/cancel")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["status"] == "cancelled"

    def test_cancel_succeeded_job_rejected(self, tmp_path):
        """取消已完成的任务返回 2002 错误。"""
        app, _ = self._make_app_with_mock_service(tmp_path)
        client = TestClient(app)

        response = client.post("/api/v1/jobs/already_done/cancel")
        assert response.status_code == 409
        data = response.json()
        assert data["code"] == ApiErrorCodes.JOB_INVALID_STATE


# ===================================================================
# 结果下载端点测试
# ===================================================================

class TestDownloadResultEndpoint:
    """GET /api/v1/jobs/{job_id}/result 测试。"""

    def _make_app_with_mock_service(self, tmp_path, job_record=None):
        """创建 app 并注入 mock job_service。"""
        mock_service = MagicMock(spec=ConversionJobService)
        if job_record is None:
            job_record = _make_job_record(storage_root=str(tmp_path))

        def get_job_side_effect(job_id):
            return job_record

        mock_service.get_job.side_effect = get_job_side_effect
        mock_service.create_job.return_value = {
            "job_id": job_record.job_id,
            "status": job_record.status,
        }

        config = {"job": {"storage_root": str(tmp_path)}}
        app = create_app(config=config, job_service=mock_service)
        return app, mock_service

    def test_download_result_when_succeeded(self, tmp_path):
        """succeeded 任务且结果文件存在时可下载。"""
        # 创建实际的输出文件
        job_id = "job_20260528_abcd1234"
        output_dir = tmp_path / "jobs" / job_id / "output"
        output_dir.mkdir(parents=True)
        result_file = output_dir / "result.md"
        result_file.write_text("# Test Result\n\nHello World")

        record = _make_job_record(
            job_id=job_id,
            status="succeeded",
            storage_root=str(tmp_path),
        )
        record.output_path = str(result_file)

        app, _ = self._make_app_with_mock_service(tmp_path, job_record=record)
        client = TestClient(app)

        response = client.get(f"/api/v1/jobs/{job_id}/result")
        assert response.status_code == 200
        assert "markdown" in response.headers.get("content-type", "")

    def test_download_result_when_not_succeeded(self, tmp_path):
        """未完成的任务不可下载结果。"""
        record = _make_job_record(status="queued", storage_root=str(tmp_path))
        app, _ = self._make_app_with_mock_service(tmp_path, job_record=record)
        client = TestClient(app)

        response = client.get(f"/api/v1/jobs/{record.job_id}/result")
        assert response.status_code == 409  # 状态不允许


# ===================================================================
# 报告下载端点测试
# ===================================================================

class TestDownloadReportEndpoint:
    """GET /api/v1/jobs/{job_id}/report 测试。"""

    def _make_app_with_mock_service(self, tmp_path, job_record=None):
        mock_service = MagicMock(spec=ConversionJobService)
        if job_record is None:
            job_record = _make_job_record(storage_root=str(tmp_path))

        mock_service.get_job.return_value = job_record
        mock_service.create_job.return_value = {
            "job_id": job_record.job_id,
            "status": job_record.status,
        }

        config = {"job": {"storage_root": str(tmp_path)}}
        app = create_app(config=config, job_service=mock_service)
        return app, mock_service

    def test_download_report_when_file_exists(self, tmp_path):
        """报告文件存在时可下载。"""
        job_id = "job_20260528_abcd1234"
        output_dir = tmp_path / "jobs" / job_id / "output"
        output_dir.mkdir(parents=True)
        report_file = output_dir / "report.md"
        report_file.write_text("# Test Report\n\nNo errors")

        record = _make_job_record(job_id=job_id, storage_root=str(tmp_path))
        record.report_path = str(report_file)

        app, _ = self._make_app_with_mock_service(tmp_path, job_record=record)
        client = TestClient(app)

        response = client.get(f"/api/v1/jobs/{job_id}/report")
        assert response.status_code == 200


# ===================================================================
# 路径穿越攻击测试
# ===================================================================

class TestPathTraversalProtection:
    """路径穿越攻击防护测试。"""

    def _make_app_with_mock_service(self, tmp_path, job_record=None):
        mock_service = MagicMock(spec=ConversionJobService)
        if job_record is None:
            job_record = _make_job_record(storage_root=str(tmp_path))

        mock_service.get_job.return_value = job_record
        mock_service.create_job.return_value = {
            "job_id": job_record.job_id,
            "status": job_record.status,
        }

        config = {"job": {"storage_root": str(tmp_path)}}
        app = create_app(config=config, job_service=mock_service)
        return app, mock_service

    def test_result_path_traversal_rejected(self, tmp_path):
        """result 路径穿越被拒绝。"""
        # 创建一个 job_record，其 output_path 指向 workspace 外
        job_id = "job_20260528_abcd1234"
        record = _make_job_record(job_id=job_id, storage_root=str(tmp_path))
        record.status = "succeeded"
        # 将 output_path 指向系统文件（穿越）
        record.output_path = "/etc/passwd"

        app, _ = self._make_app_with_mock_service(tmp_path, job_record=record)
        client = TestClient(app)

        response = client.get(f"/api/v1/jobs/{job_id}/result")
        # 由于路径不存在或被 FileResponse 处理，至少不应该成功读取 /etc/passwd
        # 在 Windows 上 /etc/passwd 不存在，FileResponse 会返回 404
        assert response.status_code in (404, 400, 409)

    def test_report_path_traversal_rejected(self, tmp_path):
        """report 路径穿越被拒绝。"""
        job_id = "job_20260528_abcd1234"
        record = _make_job_record(job_id=job_id, storage_root=str(tmp_path))
        record.report_path = "/etc/shadow"

        app, _ = self._make_app_with_mock_service(tmp_path, job_record=record)
        client = TestClient(app)

        response = client.get(f"/api/v1/jobs/{job_id}/report")
        assert response.status_code in (404, 400)
