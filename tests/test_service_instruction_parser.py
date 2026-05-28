"""BI-02: 指令解析器（InstructionParser）测试。"""

import pytest

from docconv.service.instruction_parser import (
    InstructionParser,
    ParsedInstruction,
    INSTRUCTION_MAX_LENGTH,
)


@pytest.fixture()
def parser():
    return InstructionParser()


class TestBasicCommands:
    """基础命令按钮测试。"""

    def test_help(self, parser):
        result = parser.parse("/help")
        assert result.action == "help"
        assert result.rejected is False

    def test_start(self, parser):
        result = parser.parse("/start")
        assert result.action == "help"

    def test_status(self, parser):
        result = parser.parse("/status")
        assert result.action == "status"
        assert result.rejected is False

    def test_cancel(self, parser):
        result = parser.parse("/cancel")
        assert result.action == "cancel"
        assert result.rejected is False

    def test_convert(self, parser):
        result = parser.parse("/convert")
        assert result.action == "convert"
        assert result.options == {}

    def test_empty_input(self, parser):
        result = parser.parse("")
        assert result.action == "unknown"
        assert result.help_text != ""

    def test_none_input(self, parser):
        result = parser.parse(None)  # type: ignore
        assert result.action == "unknown"


class TestConvertWithParams:
    """带参数的 /convert 指令测试。"""

    def test_convert_sensitive(self, parser):
        result = parser.parse("/convert 敏感模式")
        assert result.action == "convert"
        assert result.options.get("sensitive_mode") is True

    def test_convert_sensitive_english(self, parser):
        result = parser.parse("/convert sensitive")
        assert result.options.get("sensitive_mode") is True

    def test_convert_model_fast(self, parser):
        result = parser.parse("/convert fast")
        assert result.options.get("model") == "fast"

    def test_convert_model_high(self, parser):
        result = parser.parse("/convert 高质量")
        assert result.options.get("model") == "high"

    def test_convert_dpi(self, parser):
        result = parser.parse("/convert dpi=300")
        assert result.options.get("dpi") == 300

    def test_convert_dpi_with_colon(self, parser):
        result = parser.parse("/convert dpi: 200")
        assert result.options.get("dpi") == 200

    def test_convert_dry_run(self, parser):
        result = parser.parse("/convert dry-run")
        assert result.options.get("dry_run") is True

    def test_convert_output_format(self, parser):
        result = parser.parse("/convert 转成 Markdown")
        assert result.options.get("output_format") == "markdown"

    def test_convert_multiple_params(self, parser):
        result = parser.parse("/convert 敏感模式 dpi=300 fast")
        assert result.options.get("sensitive_mode") is True
        assert result.options.get("dpi") == 300
        assert result.options.get("model") == "fast"


class TestPlainTextInput:
    """纯文本输入测试。"""

    def test_plain_convert_keyword(self, parser):
        result = parser.parse("转成 Markdown")
        assert result.action == "convert"

    def test_plain_convert_english(self, parser):
        result = parser.parse("convert this to markdown")
        assert result.action == "convert"


class TestRejection:
    """非白名单指令拒绝测试。"""

    def test_shell_rm_rejected(self, parser):
        result = parser.parse("rm -rf /")
        assert result.rejected is True

    def test_shell_eval_rejected(self, parser):
        result = parser.parse("eval something")
        assert result.rejected is True

    def test_shell_pipe_rejected(self, parser):
        result = parser.parse("cmd1 | cmd2")
        assert result.rejected is True

    def test_path_traversal_rejected(self, parser):
        result = parser.parse("/../etc/passwd")
        assert result.rejected is True

    def test_unknown_text_rejected(self, parser):
        result = parser.parse("hello world random text")
        assert result.rejected is True
        assert result.help_text != ""

    def test_unknown_command_rejected(self, parser):
        result = parser.parse("/unknown")
        assert result.rejected is True

    def test_reject_reason_included(self, parser):
        result = parser.parse("rm -rf /")
        assert result.reject_reason != ""


class TestLengthLimit:
    """指令长度限制测试。"""

    def test_exceed_length(self, parser):
        long_text = "/convert " + "x" * (INSTRUCTION_MAX_LENGTH + 1)
        result = parser.parse(long_text)
        assert result.rejected is True
        assert "超过" in result.reject_reason

    def test_at_limit(self, parser):
        # 刚好等于限制
        text = "x" * INSTRUCTION_MAX_LENGTH
        result = parser.parse(text)
        # 可能因为不包含关键词而被拒绝，但不应该因为长度
        assert "超过" not in result.reject_reason


class TestHelpText:
    """帮助文本测试。"""

    def test_help_contains_convert(self, parser):
        result = parser.parse("/help")
        assert "/convert" in result.help_text

    def test_help_contains_status(self, parser):
        result = parser.parse("/help")
        assert "/status" in result.help_text

    def test_help_contains_cancel(self, parser):
        result = parser.parse("/help")
        assert "/cancel" in result.help_text
