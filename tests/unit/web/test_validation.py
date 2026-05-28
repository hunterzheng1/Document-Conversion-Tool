"""请求校验辅助函数单元测试。"""

from __future__ import annotations

import pytest

from docconv.web.api.validation import (
    validate_file_extension,
    validate_file_size,
    validate_dpi,
    validate_concurrency,
    validate_instruction,
    validate_model_profile,
    ValidationError,
)
from docconv.web.api.schemas import ApiErrorCodes


# ===================================================================
# 文件扩展名校验测试
# ===================================================================

class TestValidateFileExtension:
    """validate_file_extension 测试。"""

    def test_valid_pdf(self):
        validate_file_extension("test.pdf")  # should not raise

    def test_valid_pdf_uppercase(self):
        validate_file_extension("test.PDF")  # should not raise

    def test_reject_txt(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_file_extension("test.txt")
        assert exc_info.value.code == ApiErrorCodes.UNSUPPORTED_FILE_TYPE

    def test_reject_no_extension(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_file_extension("testfile")
        assert exc_info.value.code == ApiErrorCodes.UNSUPPORTED_FILE_TYPE

    def test_reject_empty_filename(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_file_extension("")
        assert exc_info.value.code == ApiErrorCodes.INVALID_PARAMETER


# ===================================================================
# 文件大小校验测试
# ===================================================================

class TestValidateFileSize:
    """validate_file_size 测试。"""

    def test_within_limit(self):
        validate_file_size(10 * 1024 * 1024, max_size_mb=100)  # 10MB, OK

    def test_exceeds_limit(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_file_size(200 * 1024 * 1024, max_size_mb=100)  # 200MB > 100MB
        assert exc_info.value.code == ApiErrorCodes.FILE_TOO_LARGE

    def test_exact_limit(self):
        """等于限制大小时应该通过。"""
        validate_file_size(100 * 1024 * 1024, max_size_mb=100)  # exactly 100MB


# ===================================================================
# DPI 校验测试
# ===================================================================

class TestValidateDpi:
    """validate_dpi 测试。"""

    def test_none_returns_default(self):
        assert validate_dpi(None) == 200

    def test_valid_dpi(self):
        assert validate_dpi(200) == 200

    def test_min_dpi(self):
        assert validate_dpi(100) == 100

    def test_max_dpi(self):
        assert validate_dpi(400) == 400

    def test_dpi_below_min(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_dpi(99)
        assert exc_info.value.code == ApiErrorCodes.INVALID_PARAMETER

    def test_dpi_above_max(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_dpi(401)
        assert exc_info.value.code == ApiErrorCodes.INVALID_PARAMETER


# ===================================================================
# 并发数校验测试
# ===================================================================

class TestValidateConcurrency:
    """validate_concurrency 测试。"""

    def test_none_returns_default(self):
        assert validate_concurrency(None) == 2

    def test_valid_concurrency(self):
        assert validate_concurrency(3) == 3

    def test_min_concurrency(self):
        assert validate_concurrency(1) == 1

    def test_max_concurrency(self):
        assert validate_concurrency(5) == 5

    def test_concurrency_below_min(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_concurrency(0)
        assert exc_info.value.code == ApiErrorCodes.INVALID_PARAMETER

    def test_concurrency_above_max(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_concurrency(6)
        assert exc_info.value.code == ApiErrorCodes.INVALID_PARAMETER


# ===================================================================
# 指令长度校验测试
# ===================================================================

class TestValidateInstruction:
    """validate_instruction 测试。"""

    def test_none_returns_empty(self):
        assert validate_instruction(None) == ""

    def test_short_instruction(self):
        assert validate_instruction("转成 Markdown") == "转成 Markdown"

    def test_exact_max_length(self):
        instruction = "x" * 1000
        assert validate_instruction(instruction) == instruction

    def test_over_max_length(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_instruction("x" * 1001)
        assert exc_info.value.code == ApiErrorCodes.INVALID_PARAMETER


# ===================================================================
# 模型档位校验测试
# ===================================================================

class TestValidateModelProfile:
    """validate_model_profile 测试。"""

    def test_none_returns_default(self):
        assert validate_model_profile(None) == "auto"

    def test_valid_profiles(self):
        assert validate_model_profile("auto") == "auto"
        assert validate_model_profile("primary") == "primary"
        assert validate_model_profile("economy") == "economy"
        assert validate_model_profile("fallback") == "fallback"

    def test_invalid_profile(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_model_profile("ultra")
        assert exc_info.value.code == ApiErrorCodes.INVALID_PARAMETER
