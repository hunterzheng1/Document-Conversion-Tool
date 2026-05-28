"""状态管理相关异常类和错误码。

错误码对照表：
  ST1001 - StateFormatError：state.json 缺失必填字段
  ST2001 - StateIrrecoverableError：state 和 artifacts 均不可用
  ST5001 - StateWriteError：原子写入失败
  ST5002 - ArtifactWriteError：页面产物写入失败
"""

from __future__ import annotations


class StateError(Exception):
    """状态管理基类异常。"""

    error_code: str = "ST0000"

    def __init__(self, message: str, error_code: str | None = None):
        super().__init__(message)
        if error_code is not None:
            self.error_code = error_code
        self.message = message


class StateFormatError(StateError):
    """状态格式无效：state.json 缺失必填字段或格式损坏。"""

    error_code = "ST1001"

    def __init__(self, message: str):
        super().__init__(message, error_code=self.error_code)


class StateIrrecoverableError(StateError):
    """状态不可恢复：state 和 artifacts 均不可用。"""

    error_code = "ST2001"

    def __init__(self, message: str):
        super().__init__(message, error_code=self.error_code)


class StateWriteError(StateError):
    """状态写入失败：原子写入或 rename 失败。"""

    error_code = "ST5001"

    def __init__(self, message: str):
        super().__init__(message, error_code=self.error_code)


class ArtifactWriteError(StateError):
    """页面产物写入失败。"""

    error_code = "ST5002"

    def __init__(self, message: str):
        super().__init__(message, error_code=self.error_code)
