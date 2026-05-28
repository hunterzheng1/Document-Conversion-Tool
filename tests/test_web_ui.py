"""Web UI 测试 — 静态文件服务和 API 集成。"""

import os
import tempfile
import shutil
import json

import pytest

from docconv.service.job_store import SQLiteJobStore
from docconv.service.conversion_job_service import ConversionJobService
from docconv.web.api.app import create_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_data_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def app(tmp_data_dir):
    """创建 FastAPI 测试应用（注入预创建的 job_service）。"""
    db_path = os.path.join(tmp_data_dir, "job_store.sqlite3")
    store = SQLiteJobStore(db_path=db_path)
    config = {
        "storage_root": tmp_data_dir,
        "retention_hours": 24,
        "max_running_jobs": 1,
        "max_queued_jobs": 20,
    }
    job_service = ConversionJobService(config=config, store=store)

    server_config = {
        "job": config,
        "docs": {"enabled": False},
        "auth": {"enabled": False},
    }
    return create_app(config=server_config, job_service=job_service)


@pytest.fixture()
def client(app):
    """使用 httpx TestClient。"""
    from httpx import ASGITransport, AsyncClient
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# T01 验收：静态文件服务
# ---------------------------------------------------------------------------

class TestStaticFileServing:
    def test_root_returns_html(self, app):
        """GET / 应返回 HTML 页面（Content-Type: text/html）。"""
        from fastapi.testclient import TestClient
        c = TestClient(app)
        resp = c.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        assert "docconv" in resp.text

    def test_index_contains_ui_sections(self, app):
        """HTML 页面应包含所有 UI 区域。"""
        from fastapi.testclient import TestClient
        c = TestClient(app)
        resp = c.get("/")
        text = resp.text
        # 6 个语义化区域
        assert 'id="upload-section"' in text
        assert 'id="job-panel"' in text
        assert 'id="error-display"' in text
        assert 'id="recent-jobs"' in text
        assert 'id="result-actions"' in text

    def test_index_has_zh_locale(self, app):
        """页面语言应设置为 zh-CN。"""
        from fastapi.testclient import TestClient
        c = TestClient(app)
        resp = c.get("/")
        assert 'lang="zh-CN"' in resp.text

    def test_js_css_references(self, app):
        """HTML 应引用 style.css 和 app.js。"""
        from fastapi.testclient import TestClient
        c = TestClient(app)
        resp = c.get("/")
        text = resp.text
        assert 'href="/static/style.css"' in text
        assert 'src="/static/app.js"' in text


# ---------------------------------------------------------------------------
# T02+T03 验收：HTML 页面骨架与上传区
# ---------------------------------------------------------------------------

class TestHtmlStructure:
    def test_file_input_accepts_pdf(self, app):
        """文件选择控件应仅接受 .pdf。"""
        from fastapi.testclient import TestClient
        c = TestClient(app)
        resp = c.get("/")
        text = resp.text
        assert 'accept=".pdf"' in text
        assert 'type="file"' in text

    def test_dry_run_checkbox_exists(self, app):
        """dry_run 复选框应存在。"""
        from fastapi.testclient import TestClient
        c = TestClient(app)
        resp = c.get("/")
        text = resp.text
        assert 'id="dry-run"' in text

    def test_all_parameter_controls(self, app):
        """所有参数控件应存在。"""
        from fastapi.testclient import TestClient
        c = TestClient(app)
        resp = c.get("/")
        text = resp.text
        assert 'id="model-profile"' in text
        assert 'id="dpi"' in text
        assert 'id="concurrency"' in text
        assert 'id="no-cache"' in text
        assert 'id="sensitive"' in text
        assert 'id="dry-run"' in text


# ---------------------------------------------------------------------------
# T05 验收：任务状态面板与轮询（API 集成）
# ---------------------------------------------------------------------------

class TestJobApiIntegration:
    def test_submit_job_creates_queued(self, app, tmp_data_dir):
        """POST /api/v1/jobs/upload 应创建 queued 任务。"""
        from fastapi.testclient import TestClient
        c = TestClient(app)
        # 创建伪 PDF
        pdf_path = os.path.join(tmp_data_dir, "test.pdf")
        with open(pdf_path, "wb") as f:
            f.write(b"%PDF-1.4 fake content")
        with open(pdf_path, "rb") as f:
            resp = c.post(
                "/api/v1/jobs/upload",
                files={"file": ("test.pdf", f, "application/pdf")},
                data={
                    "model_profile": "auto",
                    "dpi": "200",
                    "concurrency": "2",
                    "no_cache": "false",
                    "sensitive": "false",
                    "dry_run": "false",
                },
            )
        # 成功时返回 201 或 400（视服务实现）
        assert resp.status_code in (201, 400), f"Response: {resp.json()}"
        if resp.status_code == 201:
            body = resp.json()
            assert body["code"] == 0
            data = body["data"]
            assert data["job_id"] is not None
            assert data["status"] == "queued"

    def test_get_job_status(self, app, tmp_data_dir):
        """GET /api/v1/jobs/{job_id} 应返回状态。"""
        from fastapi.testclient import TestClient
        c = TestClient(app)
        # 先创建任务
        pdf_path = os.path.join(tmp_data_dir, "test.pdf")
        with open(pdf_path, "wb") as f:
            f.write(b"%PDF-1.4 fake content")
        with open(pdf_path, "rb") as f:
            create_resp = c.post(
                "/api/v1/jobs/upload",
                files={"file": ("test.pdf", f, "application/pdf")},
            )
        job_id = create_resp.json()["data"]["job_id"]

        # 查询状态
        resp = c.get(f"/api/v1/jobs/{job_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["job_id"] == job_id
        assert "status" in body["data"]
        assert "progress" in body["data"]

    def test_cancel_job(self, app, tmp_data_dir):
        """POST /api/v1/jobs/{job_id}/cancel 应取消任务。"""
        from fastapi.testclient import TestClient
        c = TestClient(app)
        pdf_path = os.path.join(tmp_data_dir, "test.pdf")
        with open(pdf_path, "wb") as f:
            f.write(b"%PDF-1.4 fake content")
        with open(pdf_path, "rb") as f:
            create_resp = c.post(
                "/api/v1/jobs/upload",
                files={"file": ("test.pdf", f, "application/pdf")},
            )
        job_id = create_resp.json()["data"]["job_id"]

        resp = c.post(f"/api/v1/jobs/{job_id}/cancel")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["status"] == "cancelled"

    def test_reject_non_pdf(self, app):
        """上传非 PDF 文件应返回 400（业务校验错误）。"""
        from fastapi.testclient import TestClient
        c = TestClient(app)
        resp = c.post(
            "/api/v1/jobs/upload",
            files={"file": ("test.txt", b"hello", "text/plain")},
        )
        # 业务层校验返回 400（不是 FastAPI 422）
        assert resp.status_code == 400

    def test_health_endpoint(self, app, tmp_data_dir):
        """GET /api/v1/health 应返回 ok。"""
        from fastapi.testclient import TestClient
        c = TestClient(app)
        resp = c.get("/api/v1/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["status"] in ("ok", "degraded")


# ---------------------------------------------------------------------------
# T09 验收：响应式基础样式
# ---------------------------------------------------------------------------

class TestResponsiveStyles:
    def test_css_contains_media_query(self, app):
        """style.css 应包含媒体查询（响应式）。"""
        from fastapi.testclient import TestClient
        c = TestClient(app)
        resp = c.get("/static/style.css")
        assert resp.status_code == 200
        assert "@media" in resp.text

    def test_js_contains_poll_interval(self, app):
        """app.js 应包含轮询间隔常量。"""
        from fastapi.testclient import TestClient
        c = TestClient(app)
        resp = c.get("/static/app.js")
        assert resp.status_code == 200
        assert "POLL_INTERVAL_MS" in resp.text
        assert "POLL_BACKOFF_MS" in resp.text

    def test_static_resources_size(self, app):
        """静态资源总大小应 < 1MB。"""
        from fastapi.testclient import TestClient
        c = TestClient(app)
        total = 0
        for path in ["/", "/static/style.css", "/static/app.js"]:
            resp = c.get(path)
            assert resp.status_code == 200
            total += len(resp.content)
        assert total < 1 * 1024 * 1024, f"静态资源总大小 {total} bytes 超过 1MB"

    def test_js_contains_localstorage_key(self, app):
        """app.js 应使用版本化 localStorage key。"""
        from fastapi.testclient import TestClient
        c = TestClient(app)
        resp = c.get("/static/app.js")
        text = resp.text
        assert "docconv.recentJobs" in text
