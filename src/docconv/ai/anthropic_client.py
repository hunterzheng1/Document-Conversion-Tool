"""Anthropic Claude 客户端。"""

from __future__ import annotations

import os
from typing import Any

from .base import ModelManager, TokenUsage, ModelResponse, ModelApiError, ModelTimeoutError, RateLimitError


class AnthropicClient(ModelManager):
    """Anthropic Claude 模型客户端。"""

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self._api_key = cfg.get("api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
        self._model = cfg.get("model", "claude-sonnet-4-6")
        self._max_tokens = cfg.get("max_tokens", 4096)
        self._timeout = cfg.get("timeout", 120)
        self._client: Any | None = None
        self._capabilities = cfg.get("capabilities", ["vision", "text"])

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from anthropic import AsyncAnthropic
                self._client = AsyncAnthropic(
                    api_key=self._api_key,
                    timeout=self._timeout,
                )
            except ImportError:
                raise ImportError("请安装 anthropic: pip install anthropic")
        return self._client

    async def analyze_image(
        self,
        image_path: str,
        prompt: str,
        max_tokens: int = 2000,
    ) -> ModelResponse:
        import base64

        client = self._get_client()
        mime_type = "image/png"
        if image_path.lower().endswith(".jpg") or image_path.lower().endswith(".jpeg"):
            mime_type = "image/jpeg"

        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")

        response = await client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=prompt,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime_type,
                            "data": image_data,
                        },
                    },
                    {"type": "text", "text": "请分析上述图片并返回结果。"},
                ],
            }],
        )

        text = ""
        for block in response.content:
            if block.type == "text":
                text += block.text

        usage = TokenUsage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cached_input_tokens=getattr(response.usage, "cache_read_input_tokens", 0),
        )

        return ModelResponse(
            text=text,
            model_used=self._model,
            usage=usage,
            finish_reason=response.stop_reason or "stop",
        )

    async def analyze_text(
        self,
        text: str,
        prompt: str,
        max_tokens: int = 2000,
    ) -> ModelResponse:
        client = self._get_client()

        response = await client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=prompt,
            messages=[{"role": "user", "content": text}],
        )

        text_out = ""
        for block in response.content:
            if block.type == "text":
                text_out += block.text

        usage = TokenUsage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cached_input_tokens=getattr(response.usage, "cache_read_input_tokens", 0),
        )

        return ModelResponse(
            text=text_out,
            model_used=self._model,
            usage=usage,
            finish_reason=response.stop_reason or "stop",
        )
