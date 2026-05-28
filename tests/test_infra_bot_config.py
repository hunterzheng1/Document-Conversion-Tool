"""BI-03: 配置模型与环境变量测试。"""

import os
import pytest

from docconv.infra.bot_config import (
    TelegramConfig,
    FeishuConfig,
    RateLimitConfig,
    BotIntegrationSettings,
    redact_secrets,
    _redact_token,
)


class TestRedactToken:
    """token 脱敏函数测试。"""

    def test_short_token(self):
        assert _redact_token("abc") == "***"

    def test_normal_token(self):
        result = _redact_token("abcdef1234567890")
        assert result == "abcd***7890"
        assert "abcdef1234567890" not in result

    def test_empty(self):
        assert _redact_token("") == "***"


class TestTelegramConfig:
    """Telegram 配置测试。"""

    def test_defaults(self):
        cfg = TelegramConfig()
        assert cfg.enabled is False
        assert cfg.bot_token == ""
        assert cfg.allowed_chats == []

    def test_custom(self):
        cfg = TelegramConfig(
            enabled=True,
            bot_token="test_token_12345",
            allowed_chats=["chat1", "chat2"],
        )
        assert cfg.enabled is True
        assert cfg.bot_token == "test_token_12345"
        assert len(cfg.allowed_chats) == 2

    def test_repr_redacts_token(self):
        cfg = TelegramConfig(bot_token="abcdefghij1234567890")
        r = repr(cfg)
        assert "abcdefghij1234567890" not in r
        assert "***" in r


class TestFeishuConfig:
    """飞书配置测试。"""

    def test_defaults(self):
        cfg = FeishuConfig()
        assert cfg.enabled is False
        assert cfg.app_secret == ""

    def test_repr_redacts_secret(self):
        cfg = FeishuConfig(app_secret="secret_value_1234567890")
        r = repr(cfg)
        assert "secret_value_1234567890" not in r
        assert "***" in r


class TestRateLimitConfig:
    """速率限制配置测试。"""

    def test_default(self):
        cfg = RateLimitConfig()
        assert cfg.jobs_per_minute == 5

    def test_custom(self):
        cfg = RateLimitConfig(jobs_per_minute=10)
        assert cfg.jobs_per_minute == 10


class TestBotIntegrationSettings:
    """总配置测试。"""

    def test_defaults(self):
        settings = BotIntegrationSettings()
        assert settings.telegram.enabled is False
        assert settings.feishu.enabled is False
        assert settings.send_report is True
        assert settings.rate_limit.jobs_per_minute == 5

    def test_custom(self):
        settings = BotIntegrationSettings(
            telegram=TelegramConfig(enabled=True),
            feishu=FeishuConfig(enabled=True),
            send_report=False,
        )
        assert settings.telegram.enabled is True
        assert settings.feishu.enabled is True
        assert settings.send_report is False


class TestFromEnv:
    """环境变量加载测试。"""

    def test_from_env_defaults(self, monkeypatch):
        # 清除所有相关环境变量
        for key in [
            "TELEGRAM_ENABLED", "TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_CHATS",
            "FEISHU_ENABLED", "FEISHU_APP_ID", "FEISHU_APP_SECRET",
            "INTEGRATION_RATE_LIMIT_JOBS_PER_MINUTE", "INTEGRATION_SEND_REPORT",
        ]:
            monkeypatch.delenv(key, raising=False)

        settings = BotIntegrationSettings.from_env()
        assert settings.telegram.enabled is False
        assert settings.feishu.enabled is False

    def test_from_env_telegram_enabled(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_ENABLED", "true")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "my_token_1234567890")
        monkeypatch.setenv("TELEGRAM_ALLOWED_CHATS", "chat1,chat2")
        for key in [
            "FEISHU_ENABLED", "FEISHU_APP_ID", "FEISHU_APP_SECRET",
            "INTEGRATION_RATE_LIMIT_JOBS_PER_MINUTE", "INTEGRATION_SEND_REPORT",
        ]:
            monkeypatch.delenv(key, raising=False)

        settings = BotIntegrationSettings.from_env()
        assert settings.telegram.enabled is True
        assert settings.telegram.allowed_chats == ["chat1", "chat2"]


class TestRedactSecrets:
    """统一日志脱敏函数测试。"""

    def test_redact_token_equals(self):
        text = "Error: token=abc123secret456"
        result = redact_secrets(text)
        assert "abc123secret456" not in result
        assert "***" in result

    def test_redact_bearer(self):
        text = "Authorization: Bearer eyJhbGciOiJSUzI1NiJ9"
        result = redact_secrets(text)
        assert "eyJhbGci" not in result
        assert "Bearer ***" in result

    def test_redact_api_key(self):
        text = "api_key=sk-1234567890abcdef"
        result = redact_secrets(text)
        assert "sk-1234567890abcdef" not in result

    def test_redact_app_secret(self):
        text = "app_secret: my_secret_value_123"
        result = redact_secrets(text)
        assert "my_secret_value_123" not in result

    def test_no_secrets_unchanged(self):
        text = "normal log message without secrets"
        result = redact_secrets(text)
        assert result == text
