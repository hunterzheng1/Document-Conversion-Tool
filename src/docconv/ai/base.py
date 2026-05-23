"""AI 模型基础抽象类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class ModelTimeoutError(Exception):
    """模型调用超时。"""


class RateLimitError(Exception):
    """API 限流。"""


class ModelApiError(Exception):
    """API 调用失败。"""


class ModelNotFoundError(Exception):
    """模型不存在。"""


class ValidationError(Exception):
    """质量验证失败。"""


@dataclass
class TokenUsage:
    """Token 使用统计。"""
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class ModelResponse:
    """模型响应。"""
    text: str
    model_used: str
    usage: TokenUsage
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

    async def call_vision(
        self,
        image,
        prompt: str,
        model_profile: str = "auto",
        max_retries: int = 2,
    ) -> ModelResponse:
        """调用视觉模型。兼容 PIL.Image 或路径。"""
        return await self.analyze_image(image, prompt, 2000)

    async def check_models(self) -> dict:
        """检查所有模型可用性。"""
        return {}

    def estimate_cost(self, usage: TokenUsage, model_id: str) -> float:
        """估算单次调用成本（USD）。"""
        return 0.0
