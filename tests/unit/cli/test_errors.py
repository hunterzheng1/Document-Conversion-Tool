"""CLI 错误码与脱敏输出单元测试。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))

import pytest
from docconv.cli.errors import (
    CLIError,
    CLIInvalidArgumentError,
    CLIInvalidConfigError,
    CLIStateError,
    CLINotAllowedError,
    CLIExecutionError,
    redact_output,
    handle_cli_error,
    CLI_ERR_CODES,
)


class TestErrorCodes:
    """测试 CLI 错误码常量。"""

    def test_all_codes_present(self):
        """所有错误码都已定义。"""
        assert "CLI1001" in CLI_ERR_CODES
        assert "CLI1002" in CLI_ERR_CODES
        assert "CLI2001" in CLI_ERR_CODES
        assert "CLI2002" in CLI_ERR_CODES
        assert "CLI5001" in CLI_ERR_CODES


class TestCustomExceptions:
    """测试自定义异常类。"""

    def test_cli_error_base(self):
        """CLIError 基类。"""
        exc = CLIError("test message")
        assert "[CLI5001]" in str(exc)
        assert "test message" in str(exc)

    def test_invalid_argument_error(self):
        """CLI1001: 参数校验失败。"""
        exc = CLIInvalidArgumentError("port out of range")
        assert "[CLI1001]" in str(exc)
        assert exc.error_code == "CLI1001"

    def test_invalid_config_error(self):
        """CLI1002: 配置校验失败。"""
        exc = CLIInvalidConfigError("storage.root not found")
        assert "[CLI1002]" in str(exc)
        assert exc.error_code == "CLI1002"

    def test_state_error(self):
        """CLI2001: 任务不存在。"""
        exc = CLIStateError("job not found")
        assert "[CLI2001]" in str(exc)
        assert exc.error_code == "CLI2001"

    def test_not_allowed_error(self):
        """CLI2002: 操作不允许。"""
        exc = CLINotAllowedError("cannot cancel completed task")
        assert "[CLI2002]" in str(exc)
        assert exc.error_code == "CLI2002"

    def test_execution_error(self):
        """CLI5001: 执行错误。"""
        exc = CLIExecutionError("uvicorn not installed")
        assert "[CLI5001]" in str(exc)
        assert exc.error_code == "CLI5001"

    def test_custom_error_code_override(self):
        """支持自定义错误码覆盖。"""
        exc = CLIError("custom", error_code="CLI9999")
        assert "[CLI9999]" in str(exc)


class TestRedactOutput:
    """测试脱敏输出函数。"""

    def test_no_secrets_passes_through(self):
        """不含密钥的文本原样返回。"""
        text = "Hello, this is a normal message."
        assert redact_output(text) == text

    def test_redact_api_key_sk(self):
        """脱敏 sk- 开头的 API Key。"""
        text = "API key is sk-abcdefghijklmnopqrstuvwxyz1234"
        result = redact_output(text)
        assert "sk-" not in result
        assert "[REDACTED-API-KEY]" in result

    def test_redact_bot_token_xoxb(self):
        """脱敏 xoxb- bot token。"""
        text = "Token: xoxb-1234567890-abcdefghijk"
        result = redact_output(text)
        assert "xoxb-" not in result
        assert "[REDACTED-BOT-TOKEN]" in result

    def test_redact_token_xoxe(self):
        """脱敏 xoxe- token。"""
        text = "Auth: xoxe-abcdefghijklmnopqrstuv"
        result = redact_output(text)
        assert "xoxe-" not in result

    def test_redact_github_token(self):
        """脱敏 ghp_ GitHub token。"""
        text = "Token: ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij"
        result = redact_output(text)
        assert "ghp_" not in result
        assert "[REDACTED-GH-TOKEN]" in result

    def test_redact_gitlab_token(self):
        """脱敏 glpat- GitLab token。"""
        text = "Token: glpat-ABCDEFGHIJKLMNOPQRST"
        result = redact_output(text)
        assert "glpat-" not in result
        assert "[REDACTED-GL-TOKEN]" in result

    def test_multiple_secrets(self):
        """同时脱敏多种密钥。"""
        text = "key1=sk-aaaaaaaaaaaaaaaaaaaaaaaa key2=xoxb-bbbbbbbbbbbbbbbbbbbb"
        result = redact_output(text)
        assert "sk-" not in result
        assert "xoxb-" not in result
        assert "[REDACTED-API-KEY]" in result
        assert "[REDACTED-BOT-TOKEN]" in result

    def test_config_path_not_redacted(self):
        """配置路径不被脱敏。"""
        text = "Config path: /etc/docconv/config.yaml"
        result = redact_output(text)
        assert result == text


class TestHandleCliError:
    """测试统一错误处理。"""

    def test_cli_error_exits_with_code_1(self):
        """CLIError 处理时退出码为 1。"""
        with pytest.raises(SystemExit) as exc_info:
            handle_cli_error(CLIInvalidArgumentError("bad port"))
        assert exc_info.value.code == 1

    def test_non_cli_error_also_exits_1(self):
        """非 CLIError 异常也退出码 1。"""
        with pytest.raises(SystemExit) as exc_info:
            handle_cli_error(ValueError("some error"))
        assert exc_info.value.code == 1
