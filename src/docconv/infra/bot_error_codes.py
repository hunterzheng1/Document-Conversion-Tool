"""平台集成统一错误码与日志脱敏框架。

定义所有错误码，确保对应场景正确返回。
日志中不出现 bot token、app secret、access token。
审计日志包含 platform、chat hash、job_id、事件类型、耗时、错误类型。
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from docconv.infra.bot_config import redact_secrets

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 错误码定义
# ---------------------------------------------------------------------------


class BotErrorCodes:
    """Bot 集成错误码。"""

    # 来源/权限错误 (3xxx)
    AUTH_UNAUTHORIZED = "3001"        # 来源未授权
    AUTH_WEBHOOK_FAILED = "3002"      # Webhook 验证失败

    # 文件/指令错误 (1xxx)
    FILE_UNSUPPORTED = "1001"         # 文件类型不支持
    INSTRUCTION_UNSUPPORTED = "1004"  # 指令不支持

    # 下载/发送错误 (4xxx)
    DOWNLOAD_FAILED = "4001"          # 下载失败
    SEND_FAILED = "4002"              # 发送失败


# ---------------------------------------------------------------------------
# 错误响应
# ---------------------------------------------------------------------------


@dataclass
class BotErrorResponse:
    """标准化错误响应。"""
    error_code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.error_code,
                "message": redact_secrets(self.message),
                "details": self.details,
            }
        }


# ---------------------------------------------------------------------------
# 审计日志
# ---------------------------------------------------------------------------


def hash_chat_id(chat_id: str) -> str:
    """对 chat_id 进行哈希，用于审计日志。"""
    return hashlib.sha256(chat_id.encode()).hexdigest()[:8]


@dataclass
class AuditEvent:
    """审计日志事件。"""
    platform: str = ""
    chat_hash: str = ""
    job_id: str = ""
    event_type: str = ""       # "received", "downloaded", "job_created", "callback_sent", "failed"
    duration_ms: float = 0
    error_type: str = ""
    error_code: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def log_audit(event: AuditEvent) -> None:
    """记录审计日志。

    所有日志输出自动脱敏 token、secret、access_token。
    """
    log_entry = {
        "platform": event.platform,
        "chat_hash": event.chat_hash,
        "job_id": event.job_id,
        "event_type": event.event_type,
        "duration_ms": event.duration_ms,
        "error_type": redact_secrets(event.error_type) if event.error_type else "",
        "error_code": event.error_code,
    }
    if event.extra:
        # 脱敏 extra 中的敏感信息
        redacted_extra = {k: redact_secrets(str(v)) if isinstance(v, str) else v for k, v in event.extra.items()}
        log_entry["extra"] = redacted_extra

    if event.error_code:
        logger.warning("Bot audit: %s", log_entry)
    else:
        logger.info("Bot audit: %s", log_entry)


class AuditTimer:
    """审计用计时器上下文管理器。"""

    def __init__(self, event: AuditEvent):
        self.event = event
        self._start = 0.0

    def __enter__(self) -> "AuditTimer":
        self._start = time.time()
        return self

    def __exit__(self, *args: Any) -> None:
        self.event.duration_ms = (time.time() - self._start) * 1000

