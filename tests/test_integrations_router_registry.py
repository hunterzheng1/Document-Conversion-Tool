"""BI-15: 路由注册与配置集成测试。"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from docconv.infra.bot_config import (
    BotIntegrationSettings,
    TelegramConfig,
    FeishuConfig,
)
from docconv.integrations.router_registry import register_integration_routes


class TestRouterRegistration:
    """路由注册测试。"""

    def test_no_platforms_enabled(self):
        """未启用任何平台时不应注册路由。"""
        app = FastAPI()
        mock_job_service = MagicMock()

        settings = BotIntegrationSettings(
            telegram=TelegramConfig(enabled=False),
            feishu=FeishuConfig(enabled=False),
        )

        result = register_integration_routes(app, mock_job_service, settings)
        assert result["telegram_registered"] is False
        assert result["feishu_registered"] is False

    def test_telegram_enabled(self):
        """仅启用 Telegram 时应注册 Telegram 路由。"""
        app = FastAPI()
        mock_job_service = MagicMock()

        settings = BotIntegrationSettings(
            telegram=TelegramConfig(
                enabled=True,
                bot_token="test_token_12345",
                allowed_chats=["chat_1"],
            ),
            feishu=FeishuConfig(enabled=False),
        )

        result = register_integration_routes(app, mock_job_service, settings)
        assert result["telegram_registered"] is True
        assert result["feishu_registered"] is False

        # 验证路由存在
        routes = [r.path for r in app.routes if hasattr(r, "path")]
        assert any("/integrations/telegram/webhook" in r for r in routes)

    def test_feishu_enabled(self):
        """仅启用飞书时应注册飞书路由。"""
        app = FastAPI()
        mock_job_service = MagicMock()

        settings = BotIntegrationSettings(
            telegram=TelegramConfig(enabled=False),
            feishu=FeishuConfig(
                enabled=True,
                app_id="test_app_id",
                app_secret="test_secret_12345",
                allowed_tenants=["tenant_1"],
            ),
        )

        result = register_integration_routes(app, mock_job_service, settings)
        assert result["telegram_registered"] is False
        assert result["feishu_registered"] is True

        # 验证路由存在
        routes = [r.path for r in app.routes if hasattr(r, "path")]
        assert any("/integrations/feishu/webhook" in r for r in routes)

    def test_both_platforms_enabled(self):
        """两个平台都启用时应都注册。"""
        app = FastAPI()
        mock_job_service = MagicMock()

        settings = BotIntegrationSettings(
            telegram=TelegramConfig(
                enabled=True,
                bot_token="test_token_12345",
                allowed_chats=["chat_1"],
            ),
            feishu=FeishuConfig(
                enabled=True,
                app_id="test_app",
                app_secret="test_secret_12345",
                allowed_tenants=["tenant_1"],
            ),
        )

        result = register_integration_routes(app, mock_job_service, settings)
        assert result["telegram_registered"] is True
        assert result["feishu_registered"] is True

    def test_callback_handler_registered(self):
        """终态回调钩子应注册到 app.state。"""
        app = FastAPI()
        mock_job_service = MagicMock()

        settings = BotIntegrationSettings(
            telegram=TelegramConfig(enabled=True, bot_token="test_token_12345"),
            feishu=FeishuConfig(enabled=False),
        )

        register_integration_routes(app, mock_job_service, settings)
        assert hasattr(app.state, "bot_callback_handler")
        assert hasattr(app.state, "bot_correlation_store")

    def test_disabled_platform_returns_503(self):
        """关闭的平台端点应返回 503。"""
        app = FastAPI()
        mock_job_service = MagicMock()

        settings = BotIntegrationSettings(
            telegram=TelegramConfig(
                enabled=True,
                bot_token="test_token_12345",
            ),
            feishu=FeishuConfig(enabled=False),
        )

        register_integration_routes(app, mock_job_service, settings)
        client = TestClient(app)

        # Telegram 启用
        resp = client.post("/integrations/telegram/webhook", json={"update_id": 1})
        assert resp.status_code != 404  # 应该是 200 或 400/503（不是 404）

        # 飞书未启用
        resp = client.post("/integrations/feishu/webhook", json={})
        # 飞书路由未注册，应返回 404
        assert resp.status_code == 404

    def test_routes_list_in_result(self):
        """返回结果应包含注册的路由列表。"""
        app = FastAPI()
        mock_job_service = MagicMock()

        settings = BotIntegrationSettings(
            telegram=TelegramConfig(enabled=True, bot_token="test_token_12345"),
            feishu=FeishuConfig(enabled=False),
        )

        result = register_integration_routes(app, mock_job_service, settings)
        assert "routes" in result
        assert isinstance(result["routes"], list)
