"""BI-09: 飞书 Webhook 端点测试。"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from docconv.integrations.feishu.webhook import router, configure


def _make_app(enabled: bool = True):
    """创建测试应用。"""
    app = FastAPI()

    mock_adapter = MagicMock()
    mock_adapter.verify_source.return_value = True
    mock_adapter.parse_message.return_value = MagicMock(
        platform="feishu",
        external_message_id="om_test_001",
        chat_id="oc_test_chat",
        sender_id="ou_test_user",
        file_id="",
        filename="",
        instruction="/help",
        job_id="",
        platform_meta={},
    )
    mock_adapter.handle_challenge.return_value = {"challenge": "test_challenge"}
    mock_adapter.check_allowlist.return_value = (True, "")
    mock_adapter.parse_instruction.return_value = MagicMock(
        action="help", options={}, rejected=False, reject_reason="",
    )

    mock_job_service = MagicMock()
    mock_job_service.create_job.return_value = {"job_id": "job_20260101_xyz789", "status": "queued"}

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


class TestFeishuWebhook:
    """飞书 Webhook 端点测试。"""

    def test_disabled_returns_503(self):
        app = _make_app(enabled=False)
        client = TestClient(app)
        resp = client.post("/integrations/feishu/webhook", json={})
        assert resp.status_code == 503

    def test_challenge_verification(self):
        """正确处理 challenge 验证事件。"""
        app = _make_app(enabled=True)
        client = TestClient(app)

        with patch("docconv.integrations.feishu.webhook._feishu_adapter") as mock:
            mock.verify_source.return_value = True
            mock.handle_challenge.return_value = {"challenge": "test_challenge_value"}
            resp = client.post("/integrations/feishu/webhook", json={
                "type": "url_verification",
                "token": "verify_token",
                "challenge": "test_challenge_value",
            })
            assert resp.status_code == 200
            assert resp.json()["challenge"] == "test_challenge_value"

    def test_challenge_invalid_token(self):
        """challenge 验证 token 错误应返回 401。"""
        app = _make_app(enabled=True)
        client = TestClient(app)

        with patch("docconv.integrations.feishu.webhook._feishu_adapter") as mock:
            mock.verify_source.return_value = False
            resp = client.post("/integrations/feishu/webhook", json={
                "type": "url_verification",
                "token": "wrong",
                "challenge": "test",
            })
            assert resp.status_code == 401

    def test_valid_message_returns_200(self):
        """正确处理消息事件，返回 200。"""
        app = _make_app(enabled=True)
        client = TestClient(app)
        resp = client.post("/integrations/feishu/webhook", json={
            "header": {"token": "verify_token"},
            "event": {
                "message": {
                    "chat_id": "oc_test_chat",
                    "message_id": "om_001",
                    "message_type": "text",
                    "content": json.dumps({"text": "/help"}),
                },
                "sender": {"sender_id": {"open_id": "ou_user"}},
            },
        })
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    def test_denied_tenant_returns_403(self):
        """allowlist 拒绝应返回 403。"""
        app = _make_app(enabled=True)
        client = TestClient(app)

        with patch("docconv.integrations.feishu.webhook._feishu_adapter") as mock:
            mock.verify_source.return_value = True
            mock.parse_message.return_value = MagicMock(
                platform="feishu",
                external_message_id="om_001",
                chat_id="oc_test",
                sender_id="ou_blocked",
                file_id="",
                filename="",
                instruction="",
                job_id="",
                platform_meta={},
            )
            mock.check_allowlist.return_value = (False, "来源未授权")
            resp = client.post("/integrations/feishu/webhook", json={
                "header": {},
                "event": {},
            })
            assert resp.status_code == 403

    def test_invalid_source_returns_401(self):
        """Webhook 验证失败应返回 401。"""
        app = _make_app(enabled=True)
        client = TestClient(app)

        with patch("docconv.integrations.feishu.webhook._feishu_adapter") as mock:
            mock.verify_source.return_value = False
            resp = client.post("/integrations/feishu/webhook", json={
                "header": {},
                "event": {
                    "message": {"chat_id": "oc_test", "message_id": "om_1", "message_type": "text", "content": '{"text": ""}'},
                    "sender": {"sender_id": {"open_id": "ou_1"}},
                },
            })
            assert resp.status_code == 401
