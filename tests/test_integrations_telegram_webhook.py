"""BI-06: Telegram Webhook 端点测试。"""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from docconv.integrations.telegram.webhook import router, configure


def _make_app(enabled: bool = True):
    """创建测试应用。"""
    app = FastAPI()

    # 创建 mock 依赖
    mock_adapter = MagicMock()
    mock_adapter.verify_source.return_value = True
    mock_adapter.parse_message.return_value = MagicMock(
        platform="telegram",
        external_message_id="12345",
        chat_id="chat_123",
        sender_id="user_456",
        file_id="",
        filename="",
        instruction="/convert",
        job_id="",
        platform_meta={},
    )
    mock_adapter.check_allowlist.return_value = (True, "")
    mock_adapter.parse_instruction.return_value = MagicMock(
        action="convert", options={}, rejected=False, reject_reason="",
    )

    mock_job_service = MagicMock()
    mock_job_service.create_job.return_value = {"job_id": "job_20260101_abc123", "status": "queued"}

    mock_store = MagicMock()
    mock_store.create_correlation.return_value = MagicMock()

    mock_access = MagicMock()
    mock_access.check_access.return_value = MagicMock(allowed=True, remaining=4)

    configure(
        adapter=mock_adapter,
        job_service=mock_job_service,
        correlation_store=mock_store,
        access_control=mock_access,
        enabled=enabled,
    )

    app.include_router(router)
    return app


class TestTelegramWebhook:
    """Telegram Webhook 端点测试。"""

    def test_disabled_returns_503(self):
        app = _make_app(enabled=False)
        client = TestClient(app)
        resp = client.post("/integrations/telegram/webhook", json={"update_id": 1})
        assert resp.status_code == 503

    def test_valid_text_message(self):
        """有效文本消息（无文件）应返回 ok。"""
        app = _make_app(enabled=True)
        client = TestClient(app)
        resp = client.post("/integrations/telegram/webhook", json={
            "update_id": 12345,
            "message": {
                "chat": {"id": "chat_123"},
                "from": {"id": "user_456"},
                "text": "/help",
            },
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_invalid_source_returns_401(self):
        """来源验证失败应返回 401。"""
        app = _make_app(enabled=True)
        client = TestClient(app)

        with patch("docconv.integrations.telegram.webhook._telegram_adapter") as mock:
            mock.verify_source.return_value = False
            resp = client.post("/integrations/telegram/webhook", json={"update_id": 1})
            assert resp.status_code == 401

    def test_no_message_returns_400(self):
        """无 message 字段应返回 400。"""
        app = _make_app(enabled=True)
        client = TestClient(app)

        with patch("docconv.integrations.telegram.webhook._telegram_adapter") as mock:
            mock.verify_source.return_value = True
            mock.parse_message.side_effect = ValueError("Telegram update 中无 message 字段")
            resp = client.post("/integrations/telegram/webhook", json={"update_id": 1})
            assert resp.status_code == 400

    def test_denied_chat_returns_403(self):
        """allowlist 拒绝应返回 403。"""
        app = _make_app(enabled=True)
        client = TestClient(app)

        with patch("docconv.integrations.telegram.webhook._telegram_adapter") as mock:
            mock.verify_source.return_value = True
            mock.parse_message.return_value = MagicMock(
                platform="telegram",
                external_message_id="1",
                chat_id="chat_blocked",
                sender_id="user_1",
                file_id="",
                filename="",
                instruction="",
                job_id="",
                platform_meta={},
            )
            mock.check_allowlist.return_value = (False, "来源未授权")
            resp = client.post("/integrations/telegram/webhook", json={"update_id": 1})
            assert resp.status_code == 403
