"""AI 模型基础抽象类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class TokenUsage:
    """Token 使用统计。"""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass
class ModelResponse:
    """模型响应。"""
    text: str
    model: str
    token_usage: TokenUsage | None = None
    finish_reason: str = "stop"


class ModelManager(ABC):
    """AI 模型管理器基类。"""

    @abstractmethod
    async def analyze_image(
        self,
        image_path: str,
        prompt: str,
        max_tokens: int = 2000,
    ) -> ModelResponse:
        """分析图片并返回文本结果。"""
        pass

    @abstractmethod
    async def analyze_text(
        self,
        text: str,
        prompt: str,
        max_tokens: int = 2000,
    ) -> ModelResponse:
        """分析文本并返回结果。"""
        pass
