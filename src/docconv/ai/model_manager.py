"""模型调度器：管理多模型降级链。"""

from __future__ import annotations

import logging

from .base import ModelManager, TokenUsage, ModelResponse, RateLimitError, ModelTimeoutError

logger = logging.getLogger(__name__)


# 模型定价（USD per 1K tokens，默认值）
_DEFAULT_PRICING = {
    "claude-sonnet-4-6": {"input": 0.003, "output": 0.015, "cache_read": 0.0003},
    "claude-haiku-4-5-20251001": {"input": 0.0008, "output": 0.004, "cache_read": 0.00008},
    "gpt-4o": {"input": 0.0025, "output": 0.01, "cache_read": 0.00025},
}


class ModelOrchestrator:
    """模型调度器，管理降级链。"""

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self._models: list[ModelManager] = []
        self._model_names: list[str] = []
        self._pricing: dict[str, dict] = cfg.get("pricing", _DEFAULT_PRICING)
        self._max_retries = cfg.get("max_retries", 2)
        self._timeout = cfg.get("timeout", 120)
        self._token_usage: list[TokenUsage] = []
        self._setup_models(cfg)

    def _setup_models(self, cfg: dict):
        """根据配置初始化模型降级链。"""
        from .anthropic_client import AnthropicClient
        from .openai_compatible_client import OpenAICompatibleClient

        models_config = cfg.get("models", {})

        # Vision primary
        vision_primary = models_config.get("vision_primary", {})
        provider = vision_primary.get("provider", "anthropic")
        if provider == "anthropic":
            self._models.append(AnthropicClient(vision_primary))
            self._model_names.append("anthropic-primary")
        elif provider == "openai":
            self._models.append(OpenAICompatibleClient(vision_primary))
            self._model_names.append("openai-primary")

        # Vision economy
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
                if response.usage:
                    self._token_usage.append(response.usage)
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
                if response.usage:
                    self._token_usage.append(response.usage)
                return response
            except Exception as e:
                logger.warning(f"模型 {name} 失败: {e}，尝试下一个")
                last_error = e

        raise RuntimeError(f"所有模型均失败: {last_error}")

    async def call_vision(
        self,
        image,
        prompt: str,
        model_profile: str = "auto",
        max_retries: int = 2,
    ) -> ModelResponse:
        """调用视觉模型。

        Args:
            image: PIL.Image.Image 或文件路径字符串
            prompt: prompt 文本
            model_profile: "auto" | "primary" | "economy" | "fallback"
            max_retries: 最大重试次数
        """
        if hasattr(image, "save"):
            import tempfile
            import os
            tmp_path = os.path.join(tempfile.gettempdir(), "vision_input.png")
            image.save(tmp_path, format="PNG")
            image_path = tmp_path
            cleanup = True
        else:
            image_path = image
            cleanup = False

        try:
            return await self.analyze_image(image_path, prompt, max_tokens=4096)
        finally:
            if cleanup:
                try:
                    os.remove(image_path)
                except OSError:
                    pass

    async def check_models(self) -> dict:
        """检查所有模型可用性。"""
        results = {}
        for name in self._model_names:
            available = True
            error = None
            if "anthropic" in name:
                key = os.environ.get("ANTHROPIC_API_KEY", "")
                if not key:
                    available = False
                    error = "ANTHROPIC_API_KEY 未配置"
            elif "openai" in name:
                key = os.environ.get("OPENAI_API_KEY", "")
                if not key:
                    available = False
                    error = "OPENAI_API_KEY 未配置"
            results[name] = {"available": available, "error": error}
        return results

    def estimate_cost(self, usage: TokenUsage, model_id: str) -> float:
        """估算单次调用成本（USD）。"""
        pricing = self._pricing.get(model_id, {})
        input_price = pricing.get("input", 0.003)
        output_price = pricing.get("output", 0.015)
        cache_price = pricing.get("cache_read", 0.0003)

        cost = (
            usage.input_tokens / 1000 * input_price
            + usage.output_tokens / 1000 * output_price
            + usage.cached_input_tokens / 1000 * cache_price
        )
        return round(cost, 6)

    def get_total_token_usage(self) -> TokenUsage:
        """获取累计 Token 使用量。"""
        total = TokenUsage()
        for usage in self._token_usage:
            total.input_tokens += usage.input_tokens
            total.output_tokens += usage.output_tokens
            total.cached_input_tokens += usage.cached_input_tokens
        return total
