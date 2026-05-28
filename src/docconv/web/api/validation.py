"""请求校验辅助函数。"""

from __future__ import annotations

from .schemas import ApiErrorCodes, ModelProfile


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

ALLOWED_EXTENSIONS = {".pdf"}
DPI_MIN = 100
DPI_MAX = 400
CONCURRENCY_MIN = 1
CONCURRENCY_MAX = 5
INSTRUCTION_MAX_LENGTH = 1000


class ValidationError(Exception):
    """请求校验失败异常。"""

    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


def validate_file_extension(filename: str) -> None:
    """校验文件扩展名。

    Args:
        filename: 文件名

    Raises:
        ValidationError: 扩展名不支持 (1001)
    """
    if not filename:
        raise ValidationError(
            ApiErrorCodes.INVALID_PARAMETER, "文件名不能为空"
        )

    # 提取扩展名（小写）
    if "." not in filename:
        raise ValidationError(
            ApiErrorCodes.UNSUPPORTED_FILE_TYPE,
            f"不支持的文件类型: {filename}，仅支持: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    ext = "." + filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(
            ApiErrorCodes.UNSUPPORTED_FILE_TYPE,
            f"不支持的文件类型: {ext}，仅支持: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )


def validate_file_size(size_bytes: int, max_size_mb: int = 100) -> None:
    """校验文件大小。

    Args:
        size_bytes: 文件大小（字节）
        max_size_mb: 最大允许大小（MB）

    Raises:
        ValidationError: 文件过大 (1002)
    """
    max_bytes = max_size_mb * 1024 * 1024
    if size_bytes > max_bytes:
        raise ValidationError(
            ApiErrorCodes.FILE_TOO_LARGE,
            f"文件大小 {size_bytes / 1024 / 1024:.1f} MB 超过限制 {max_size_mb} MB",
        )


def validate_dpi(dpi: int | None) -> int:
    """校验 DPI 值。

    Args:
        dpi: DPI 值，None 时使用默认值 200

    Returns:
        校验后的 DPI 值

    Raises:
        ValidationError: DPI 越界 (1003)
    """
    if dpi is None:
        return 200
    if dpi < DPI_MIN or dpi > DPI_MAX:
        raise ValidationError(
            ApiErrorCodes.INVALID_PARAMETER,
            f"DPI 必须在 {DPI_MIN}-{DPI_MAX} 之间，当前值: {dpi}",
        )
    return dpi


def validate_concurrency(concurrency: int | None) -> int:
    """校验并发数。

    Args:
        concurrency: 并发数，None 时使用默认值 2

    Returns:
        校验后的并发数

    Raises:
        ValidationError: 并发数越界 (1003)
    """
    if concurrency is None:
        return 2
    if concurrency < CONCURRENCY_MIN or concurrency > CONCURRENCY_MAX:
        raise ValidationError(
            ApiErrorCodes.INVALID_PARAMETER,
            f"并发数必须在 {CONCURRENCY_MIN}-{CONCURRENCY_MAX} 之间，当前值: {concurrency}",
        )
    return concurrency


def validate_instruction(instruction: str | None) -> str:
    """校验转换指令。

    Args:
        instruction: 转换指令，None 时返回空字符串

    Returns:
        校验后的指令字符串

    Raises:
        ValidationError: 指令超长 (1003)
    """
    if instruction is None:
        return ""
    if len(instruction) > INSTRUCTION_MAX_LENGTH:
        raise ValidationError(
            ApiErrorCodes.INVALID_PARAMETER,
            f"指令长度超过 {INSTRUCTION_MAX_LENGTH} 字符",
        )
    return instruction


def validate_model_profile(profile: str | None) -> str:
    """校验模型档位。

    Args:
        profile: 模型档位字符串，None 时使用默认值 "auto"

    Returns:
        校验后的模型档位

    Raises:
        ValidationError: 档位无效 (1003)
    """
    if profile is None:
        return "auto"
    try:
        ModelProfile(profile)
    except ValueError:
        valid = ", ".join(m.value for m in ModelProfile)
        raise ValidationError(
            ApiErrorCodes.INVALID_PARAMETER,
            f"无效的模型档位: {profile}，可选: {valid}",
        )
    return profile
