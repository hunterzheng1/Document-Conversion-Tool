"""CLI 错误码常量与自定义异常类。"""

from __future__ import annotations

import re
import sys


# ---------------------------------------------------------------------------
# 错误码常量
# ---------------------------------------------------------------------------
CLI_ERR_CODES = {
    "CLI1001": "参数校验失败",
    "CLI1002": "配置校验失败",
    "CLI2001": "任务不存在",
    "CLI2002": "操作不允许",
    "CLI5001": "执行错误",
}


class CLIError(Exception):
    """CLI 错误基类。"""

    error_code: str = "CLI5001"

    def __init__(self, message: str, error_code: str | None = None):
        self.error_code = error_code or self.error_code
        desc = CLI_ERR_CODES.get(self.error_code, "未知错误")
        super().__init__(f"[{self.error_code}] {desc}: {message}")


class CLIInvalidArgumentError(CLIError):
    """CLI1001: 参数校验失败（如 port 越界）。"""
    error_code = "CLI1001"


class CLIInvalidConfigError(CLIError):
    """CLI1002: 配置校验失败（如 storage.root 不存在）。"""
    error_code = "CLI1002"


class CLIStateError(CLIError):
    """CLI2001: 任务不存在。"""
    error_code = "CLI2001"


class CLINotAllowedError(CLIError):
    """CLI2002: 操作不允许（如取消已完成任务）。"""
    error_code = "CLI2002"


class CLIExecutionError(CLIError):
    """CLI5001: 执行错误（如 uvicorn 未安装）。"""
    error_code = "CLI5001"


# ---------------------------------------------------------------------------
# 脱敏工具
# ---------------------------------------------------------------------------

# 常见密钥模式
_SECRET_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "[REDACTED-API-KEY]"),
    (re.compile(r"xoxb-[A-Za-z0-9\-]+"), "[REDACTED-BOT-TOKEN]"),
    (re.compile(r"xoxe-[A-Za-z0-9\-]+"), "[REDACTED-TOKEN]"),
    (re.compile(r"ghp_[A-Za-z0-9]{36}"), "[REDACTED-GH-TOKEN]"),
    (re.compile(r"glpat-[A-Za-z0-9\-]{20,}"), "[REDACTED-GL-TOKEN]"),
]


def redact_output(text: str) -> str:
    """识别并替换文本中的常见密钥模式。

    Args:
        text: 原始文本

    Returns:
        脱敏后的文本
    """
    result = text
    for pattern, replacement in _SECRET_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def handle_cli_error(exc: Exception) -> None:
    """统一处理 CLI 错误：脱敏后输出到 stderr 并设置退出码。"""
    msg = str(exc)
    if isinstance(exc, CLIError):
        msg = redact_output(msg)
        click_echo_safe(f"错误: {msg}", err=True)
        sys.exit(1)
    else:
        # 非 CLIError 异常也做脱敏处理
        msg = redact_output(msg)
        click_echo_safe(f"错误: [{CLI_ERR_CODES['CLI5001']}] {msg}", err=True)
        sys.exit(1)


def click_echo_safe(message: str, err: bool = False) -> None:
    """安全地输出到 click（避免 import click 循环依赖）。"""
    try:
        import click
        click.echo(message, err=err)
    except Exception:
        if err:
            sys.stderr.write(message + "\n")
        else:
            sys.stdout.write(message + "\n")
