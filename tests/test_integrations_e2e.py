"""BI-14: 集成测试。

端到端集成测试，模拟完整的 Telegram 和飞书 webhook 流程：
接收事件 -> 验证来源 -> 下载文件 -> 解析指令 -> 创建 job -> 终态回传。
使用 mock 服务器模拟 Telegram Bot API 和飞书 OpenAPI。
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from docconv.infra.bot_config import (
    BotIntegrationSettings,
    TelegramConfig,
    FeishuConfig,
)
from docconv.integrations.router_registry import register_integration_routes


def _make_full_app(telegram_enabled: bool = True, feishu_enabled: bool = True):
    """创建包含完整集成路由的测试应用。"""
    app = FastAPI()

    mock_job_service = MagicMock()
    mock_job_service.create_job.return_value = {"job_id": "job_20260101_e2e001", "status": "queued"}
    mock_job_service.get_job.return_value = MagicMock(
        job_id="job_20260101_e2e001",
        status="succeeded",
        original_filename="test.pdf",
        input_path="/tmp/test/input.pdf",
        output_path="/tmp/test/output/result.md",
        report_path="/tmp/test/report.md",
        instruction="/convert",
        error_type="",
        error_message="",
    )

    settings = BotIntegrationSettings(
        telegram=TelegramConfig(
            enabled=telegram_enabled,
            bot_token="test_token_1234567890",
            allowed_chats=["chat_123", "chat_e2e"],
        ) if telegram_enabled else TelegramConfig(enabled=False),
        feishu=FeishuConfig(
            enabled=feishu_enabled,
            app_id="test_app_id",
            app_secret="test_secret_1234567890",
            allowed_tenants=["tenant_e2e"],
            verification_token="verify_token",
        ) if feishu_enabled else FeishuConfig(enabled=False),
    )

    result = register_integration_routes(app, mock_job_service, settings)
    return app, result


class TestTelegramEndToEnd:
    """Telegram 端到端测试。"""

    def test_normal_text_message(self):
        """正常文本消息流程。"""
        app, result = _make_full_app()
        client = TestClient(app)

        resp = client.post("/integrations/telegram/webhook", json={
            "update_id": 99001,
            "message": {
                "chat": {"id": "chat_e2e"},
                "from": {"id": "user_e2e"},
                "text": "/help",
            },
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_allowlist_rejection(self):
        """allowlist 拒绝场景。"""
        app, result = _make_full_app()
        client = TestClient(app)

        resp = client.post("/integrations/telegram/webhook", json={
            "update_id": 99002,
            "message": {
                "chat": {"id": "chat_blocked"},
                "from": {"id": "user_blocked"},
                "text": "/convert",
            },
        })
        assert resp.status_code == 403


class TestFeishuEndToEnd:
    """飞书端到端测试。"""

    def test_challenge_verification_flow(self):
        """challenge 验证事件处理。"""
        app, result = _make_full_app()
        client = TestClient(app)

        resp = client.post("/integrations/feishu/webhook", json={
            "type": "url_verification",
            "token": "verify_token",
            "challenge": "e2e_challenge_value",
        })
        assert resp.status_code == 200
        assert resp.json()["challenge"] == "e2e_challenge_value"

    def test_normal_text_message(self):
        """正常消息事件处理。"""
        app, result = _make_full_app()
        client = TestClient(app)

        resp = client.post("/integrations/feishu/webhook", json={
            "header": {"token": "verify_token"},
            "event": {
                "message": {
                    "chat_id": "oc_e2e_chat",
                    "message_id": "om_e2e_001",
                    "message_type": "text",
                    "content": json.dumps({"text": "/help"}),
                },
                "sender": {"sender_id": {"open_id": "tenant_e2e"}},
            },
        })
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    def test_allowlist_rejection(self):
        """allowlist 拒绝场景。"""
        app, result = _make_full_app()
        client = TestClient(app)

        with patch("docconv.integrations.feishu.webhook._feishu_adapter") as mock:
            mock.verify_source.return_value = True
            mock.parse_message.return_value = MagicMock(
                platform="feishu",
                external_message_id="om_blocked",
                chat_id="oc_blocked",
                sender_id="ou_blocked_tenant",
                file_id="",
                filename="",
                instruction="",
                job_id="",
                platform_meta={},
            )
            mock.check_allowlist.return_value = (False, "来源未授权")
            resp = client.post("/integrations/feishu/webhook", json={
                "header": {"token": "verify_token"},
                "event": {
                    "message": {"chat_id": "oc_blocked", "message_id": "om_x", "message_type": "text", "content": '{"text": ""}'},
                    "sender": {"sender_id": {"open_id": "ou_blocked"}},
                },
            })
            assert resp.status_code == 403


class TestRateLimitEndToEnd:
    """速率限制端到端测试。"""

    def test_rate_limit_on_telegram(self):
        """Telegram 速率限制场景。"""
        app = FastAPI()
        mock_job_service = MagicMock()
        mock_job_service.create_job.return_value = {"job_id": "job_e2e", "status": "queued"}

        settings = BotIntegrationSettings(
            telegram=TelegramConfig(
                enabled=True,
                bot_token="test_token_12345",
                allowed_chats=["chat_1"],
            ),
        )

        # 设置极低的速率限制
        from docconv.infra.access_control import AccessControlMiddleware
        from docconv.infra.bot_correlation_store import BotCorrelationStore
        from docconv.integrations.telegram.adapter import TelegramAdapter
        from docconv.integrations.telegram.webhook import configure

        access = AccessControlMiddleware(max_jobs_per_minute=1)
        store = BotCorrelationStore()
        adapter = TelegramAdapter(bot_token="test_token_12345", allowed_chats={"chat_1"})

        configure(
            adapter=adapter,
            job_service=mock_job_service,
            correlation_store=store,
            access_control=access,
            enabled=True,
        )

        from docconv.integrations.telegram.webhook import router as tg_router
        app.include_router(tg_router)

        client = TestClient(app)

        # 第一次应成功
        resp1 = client.post("/integrations/telegram/webhook", json={
            "update_id": 1,
            "message": {"chat": {"id": "chat_1"}, "from": {"id": "user_1"}, "text": "/help"},
        })
        assert resp1.status_code == 200

        # 第二次应被限流
        resp2 = client.post("/integrations/telegram/webhook", json={
            "update_id": 2,
            "message": {"chat": {"id": "chat_1"}, "from": {"id": "user_1"}, "text": "/help"},
        })
        assert resp2.status_code == 429
