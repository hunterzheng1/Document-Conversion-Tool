"""日志敏感内容脱敏工具。

提供通用的日志脱敏函数，用于隐藏 API Key、Token 等敏感信息。
"""

from __future__ import annotations

import re
from typing import Pattern

# 脱敏替换标记
REDACTED = "***REDACTED***"

# 需要脱敏的模式列表
_REDACTION_PATTERNS: list[tuple[Pattern[str], str]] = [
    # Anthropic / OpenAI API Key: sk-ant-xxx / sk-proj-xxx / sk-xxx
    (re.compile(r"sk-[A-Za-z0-9\-]{20,}"), "API_KEY"),
    # Bearer token in headers
    (re.compile(r"Bearer\s+[A-Za-z0-9\-_.]+"), "BEARER_TOKEN"),
    # Generic *_KEY=xxx or *_TOKEN=xxx in env-style
    (re.compile(r"([A-Z_]*(?:KEY|TOKEN|SECRET))\s*[=:]\s*\S+", re.IGNORECASE), None),
    # URL query parameter containing token
    (re.compile(r"([?&](?:token|api_key|apikey|access_token|key)=)[^&\s]+", re.IGNORECASE), None),
    # Authorization header
    (re.compile(r"(Authorization:\s*)\S+", re.IGNORECASE), None),
]


def redact_text(text: str) -> str:
    """对文本中的敏感信息进行脱敏。

    Args:
        text: 原始文本

    Returns:
        脱敏后的文本
    """
    if not text:
        return text

    result = text
    for pattern, label in _REDACTION_PATTERNS:
        if label is not None:
            # 简单替换为 REDACTED 标记
            result = pattern.sub(REDACTED, result)
        else:
            # 保留前缀（如变量名），只替换值
            def _replace_val(m: re.Match[str]) -> str:
                full = m.group(0)
                # 找到 = 或 : 的位置
                for sep in ("=", ":"):
                    idx = full.find(sep)
                    if idx != -1:
                        return full[: idx + 1] + REDACTED
                return REDACTED

            result = pattern.sub(_replace_val, result)

    return result


def redact_dict(data: dict[str, object]) -> dict[str, object]:
    """对字典中的敏感值进行脱敏。

    对包含 KEY、TOKEN、SECRET、PASSWORD 的键的值进行脱敏。
    """
    sensitive_keys = {"key", "token", "secret", "password", "api_key", "authorization"}
    result = {}
    for k, v in data.items():
        if any(s in k.lower() for s in sensitive_keys):
            result[k] = REDACTED
        elif isinstance(v, str):
            result[k] = redact_text(v)
        elif isinstance(v, dict):
            result[k] = redact_dict(v)
        else:
            result[k] = v
    return result
