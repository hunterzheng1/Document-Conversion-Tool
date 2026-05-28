"""机器人集成配置模型。

使用 pydantic Settings 从环境变量加载配置，
token/secret 字段在 repr 和日志中自动脱敏。
"""

from __future__ import annotations

import re
from typing import Any

try:
    from pydantic import BaseModel, Field
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:
    # pydantic 未安装时的兼容回退
    BaseModel = object  # type: ignore
    BaseSettings = object  # type: ignore
    SettingsConfigDict = {}  # type: ignore
    Field = lambda default=None, **kw: default  # type: ignore


def _redact_token(value: str) -> str:
    """对 token/secret 值进行脱敏，仅显示前后各 4 个字符。"""
    if len(value) <= 8:
        return "***"
    return value[:4] + "***" + value[-4:]


class TelegramConfig(BaseModel):
    """Telegram 平台配置。"""
    enabled: bool = False
    bot_token: str = ""
    allowed_chats: list[str] = Field(default_factory=list)
    webhook_secret: str = ""

    def __repr__(self) -> str:
        return (
            f"TelegramConfig(enabled={self.enabled}, "
            f"bot_token='{_redact_token(self.bot_token)}', "
            f"allowed_chats={self.allowed_chats})"
        )


class FeishuConfig(BaseModel):
    """飞书平台配置。"""
    enabled: bool = False
    app_id: str = ""
    app_secret: str = ""
    allowed_tenants: list[str] = Field(default_factory=list)
    verification_token: str = ""

    def __repr__(self) -> str:
        return (
            f"FeishuConfig(enabled={self.enabled}, "
            f"app_id='{self.app_id}', "
            f"app_secret='{_redact_token(self.app_secret)}', "
            f"allowed_tenants={self.allowed_tenants})"
        )


class RateLimitConfig(BaseModel):
    """速率限制配置。"""
    jobs_per_minute: int = 5


class BotIntegrationSettings:
    """机器人集成总配置。

    支持通过类方法从环境变量加载配置（需 pydantic-settings），
    也支持手动构造。
    """

    def __init__(
        self,
        telegram: TelegramConfig | None = None,
        feishu: FeishuConfig | None = None,
        rate_limit: RateLimitConfig | None = None,
        send_report: bool = True,
    ):
        self.telegram = telegram or TelegramConfig()
        self.feishu = feishu or FeishuConfig()
        self.rate_limit = rate_limit or RateLimitConfig()
        self.send_report = send_report

    @classmethod
    def from_env(cls) -> "BotIntegrationSettings":
        """从环境变量加载配置。

        环境变量：
        - TELEGRAM_ENABLED, TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_CHATS, TELEGRAM_WEBHOOK_SECRET
        - FEISHU_ENABLED, FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_ALLOWED_TENANTS, FEISHU_VERIFICATION_TOKEN
        - INTEGRATION_RATE_LIMIT_JOBS_PER_MINUTE
        - INTEGRATION_SEND_REPORT
        """
        import os

        def parse_csv(val: str) -> list[str]:
            return [x.strip() for x in val.split(",") if x.strip()] if val else []

        telegram = TelegramConfig(
            enabled=os.environ.get("TELEGRAM_ENABLED", "false").lower() == "true",
            bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
            allowed_chats=parse_csv(os.environ.get("TELEGRAM_ALLOWED_CHATS", "")),
            webhook_secret=os.environ.get("TELEGRAM_WEBHOOK_SECRET", ""),
        )

        feishu = FeishuConfig(
            enabled=os.environ.get("FEISHU_ENABLED", "false").lower() == "true",
            app_id=os.environ.get("FEISHU_APP_ID", ""),
            app_secret=os.environ.get("FEISHU_APP_SECRET", ""),
            allowed_tenants=parse_csv(os.environ.get("FEISHU_ALLOWED_TENANTS", "")),
            verification_token=os.environ.get("FEISHU_VERIFICATION_TOKEN", ""),
        )

        rate_limit = RateLimitConfig(
            jobs_per_minute=int(os.environ.get("INTEGRATION_RATE_LIMIT_JOBS_PER_MINUTE", "5")),
        )

        send_report = os.environ.get("INTEGRATION_SEND_REPORT", "true").lower() == "true"

        return cls(
            telegram=telegram,
            feishu=feishu,
            rate_limit=rate_limit,
            send_report=send_report,
        )

    def __repr__(self) -> str:
        return (
            f"BotIntegrationSettings("
            f"telegram={self.telegram}, "
            f"feishu={self.feishu}, "
            f"rate_limit={self.rate_limit}, "
            f"send_report={self.send_report})"
        )


def redact_secrets(text: str) -> str:
    """统一日志脱敏函数。

    移除文本中的 bot token、app secret、access token、Bearer token 等敏感信息。

    Args:
        text: 原始文本

    Returns:
        脱敏后的文本
    """
    patterns = [
        (r'(token[=:]\s*)\S+', r'\1***'),
        (r'(api[_-]?key[=:]\s*)\S+', r'\1***'),
        (r'(app[_-]?secret[=:]\s*)\S+', r'\1***'),
        (r'(access[_-]?token[=:]\s*)\S+', r'\1***'),
        (r'Bearer\s+\S+', 'Bearer ***'),
        (r'(bot\s+)[0-9]{8,}:[A-Za-z0-9_-]{20,}', r'\1***'),
        (r'bot[0-9]{8,}:[A-Za-z0-9_-]{20,}', 'bot***'),  # bot ID:token (no space)
    ]
    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text
