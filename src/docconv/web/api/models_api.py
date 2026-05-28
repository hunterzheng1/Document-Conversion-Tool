"""模型列表端点。"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends

from .schemas import (
    APIResponse,
    ModelListResponse,
    ModelProfileItem,
)
from .dependencies import get_server_config

logger = logging.getLogger(__name__)

router = APIRouter(tags=["models"])


@router.get(
    "/models",
    summary="列出已配置的模型档位",
    description="返回所有已配置的模型信息，不暴露 API Key。",
)
async def list_models(
    server_config: dict = Depends(get_server_config),
) -> APIResponse[ModelListResponse]:
    """列出已配置的模型列表。

    从 config.yaml 读取模型配置，仅返回名称、档位、提供者等
    非敏感信息，绝不暴露 API Key。
    """
    models_config = server_config.get("models", {})
    config_file = models_config.get("config_file", "")

    profiles = []

    # 尝试从模型配置文件读取
    if config_file and os.path.exists(config_file):
        try:
            import yaml
            with open(config_file, encoding="utf-8") as f:
                model_data = yaml.safe_load(f) or {}

            for profile_name, profile_config in model_data.items():
                if isinstance(profile_config, dict):
                    profiles.append(ModelProfileItem(
                        name=profile_name,
                        profile=profile_config.get("profile", "auto"),
                        provider=profile_config.get("provider", "unknown"),
                        available=_check_model_available(profile_config),
                    ))
        except Exception as exc:
            logger.warning(f"读取模型配置失败: {exc}")

    # 如果从配置中没有获取任何模型，使用基础配置
    if not profiles:
        default_profile = models_config.get("default_profile", "auto")
        profiles.append(ModelProfileItem(
            name="default",
            profile=default_profile,
            provider="configured",
            available=True,
        ))

    return APIResponse.success(
        data=ModelListResponse(profiles=profiles),
    )


def _check_model_available(model_config: dict) -> bool:
    """检查模型是否可用（通过环境变量判断是否配置了 API Key）。

    Args:
        model_config: 模型配置字典

    Returns:
        是否可用
    """
    provider = model_config.get("provider", "").lower()

    if "anthropic" in provider:
        return bool(os.environ.get("ANTHROPIC_API_KEY"))
    elif "openai" in provider:
        return bool(os.environ.get("OPENAI_API_KEY"))
    else:
        # 其他提供者，默认认为可用
        return True
