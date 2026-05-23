"""模型调度器：管理多模型降级链。"""

from __future__ import annotations

import logging
from pathlib import Path

from .base import ModelManager, TokenUsage, ModelResponse
from .anthropic_client import AnthropicClient
from .openai_compatible_client import OpenAICompatibleClient

logger = logging.getLogger(__name__)


class ModelOrchestrator:
    """模型调度器，管理降级链。"""

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self._models: list[ModelManager] = []
        self._model_names: list[str] = []
        self._token_usage: list[TokenUsage] = []
        self._setup_models(cfg)

    def _setup_models(self, cfg: dict):
        """根据配置初始化模型降级链。"""
        models_config = cfg.get("models", {})

        # Vision primary (默认 Anthropic Claude)
        vision_primary = models_config.get("vision_primary", {})
        provider = vision_primary.get("provider", "anthropic")
        if provider == "anthropic":
            self._models.append(AnthropicClient(vision_primary))
            self._model_names.append("anthropic-primary")
        elif provider == "openai":
            self._models.append(OpenAICompatibleClient(vision_primary))
            self._model_names.append("openai-primary")

        # Vision economy (默认 Anthropic Haiku)
        vision_economy = models_config.get("vision_economy", {})
        if vision_economy:
            econ_provider = vision_economy.get("provider", "anthropic")
            if econ_provider == "anthropic":
                self._models.append(AnthropicClient(vision_economy))
                self._model_names.append("anthropic-economy")
            elif econ_provider == "openai":
                self._models.append(OpenAICompatibleClient(vision_economy))
                self._model_names.append("openai-economy")

        # Vision fallback
        vision_fallback = models_config.get("vision_fallback", {})
        if vision_fallback:
            fallback_provider = vision_fallback.get("provider", "openai")
            if fallback_provider == "openai":
                self._models.append(OpenAICompatibleClient(vision_fallback))
                self._model_names.append("openai-fallback")
            elif fallback_provider == "anthropic":
                self._models.append(AnthropicClient(vision_fallback))
                self._model_names.append("anthropic-fallback")

        if not self._models:
            logger.warning("未配置任何模型")

    async def analyze_image(
        self,
        image_path: str,
        prompt: str,
        max_tokens: int = 2000,
    ) -> ModelResponse:
        """通过降级链分析图片。"""
        last_error: Exception | None = None

        for i, model in enumerate(self._models):
            name = self._model_names[i]
            try:
                response = await model.analyze_image(image_path, prompt, max_tokens)
                if response.token_usage:
                    self._token_usage.append(response.token_usage)
                return response
            except Exception as e:
                logger.warning(f"模型 {name} 失败: {e}，尝试下一个")
                last_error = e

        raise RuntimeError(f"所有模型均失败: {last_error}")

    async def analyze_text(
        self,
        text: str,
        prompt: str,
        max_tokens: int = 2000,
    ) -> ModelResponse:
        """通过降级链分析文本。"""
        last_error: Exception | None = None

        for i, model in enumerate(self._models):
            name = self._model_names[i]
            try:
                response = await model.analyze_text(text, prompt, max_tokens)
                if response.token_usage:
                    self._token_usage.append(response.token_usage)
                return response
            except Exception as e:
                logger.warning(f"模型 {name} 失败: {e}，尝试下一个")
                last_error = e

        raise RuntimeError(f"所有模型均失败: {last_error}")

    def get_total_token_usage(self) -> TokenUsage:
        """获取累计 Token 使用量。"""
        total = TokenUsage()
        for usage in self._token_usage:
            total.input_tokens += usage.input_tokens
            total.output_tokens += usage.output_tokens
            total.total_tokens += usage.total_tokens
        return total
