"""OpenAI 兼容客户端。"""

from __future__ import annotations

import os
from typing import Any

from .base import ModelManager, TokenUsage, ModelResponse


class OpenAICompatibleClient(ModelManager):
    """OpenAI 兼容的 API 客户端（支持 OpenAI 和兼容接口）。"""

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self._api_key = cfg.get("api_key") or os.environ.get("OPENAI_API_KEY", "")
        self._model = cfg.get("model", "gpt-4o")
        self._base_url = cfg.get("base_url")
        self._timeout = cfg.get("timeout", 120)

    def _get_client(self) -> Any:
        try:
            from openai import AsyncOpenAI
            kwargs = {"api_key": self._api_key, "timeout": self._timeout}
            if self._base_url:
                kwargs["base_url"] = self._base_url
            return AsyncOpenAI(**kwargs)
        except ImportError:
            raise ImportError("请安装 openai: pip install openai")

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

        response = await client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "请分析上述图片并返回结果。"},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{image_data}",
                            },
                        },
                    ],
                },
            ],
        )

        text = response.choices[0].message.content or ""
        usage = response.usage
        token_usage = TokenUsage(
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            cached_input_tokens=getattr(usage, "prompt_tokens_details", {}).get("cached_tokens", 0) if usage else 0,
        ) if usage else None

        return ModelResponse(
            text=text,
            model_used=self._model,
            usage=token_usage,
            finish_reason=response.choices[0].finish_reason or "stop",
        )

    async def analyze_text(
        self,
        text: str,
        prompt: str,
        max_tokens: int = 2000,
    ) -> ModelResponse:
        client = self._get_client()

        response = await client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": text},
            ],
        )

        text_out = response.choices[0].message.content or ""
        usage = response.usage
        token_usage = TokenUsage(
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            cached_input_tokens=getattr(usage, "prompt_tokens_details", {}).get("cached_tokens", 0) if usage else 0,
        ) if usage else None

        return ModelResponse(
            text=text_out,
            model_used=self._model,
            usage=token_usage,
            finish_reason=response.choices[0].finish_reason or "stop",
        )
