"""路由器注册与配置集成。

将 Telegram 和飞书路由器注册到主 FastAPI 应用，
根据配置开关选择性注册路由。
注册终态回调钩子到转换服务。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI

from docconv.infra.access_control import AccessControlMiddleware
from docconv.infra.bot_config import BotIntegrationSettings
from docconv.infra.bot_correlation_store import BotCorrelationStore
from docconv.integrations.feishu.adapter import FeishuAdapter
from docconv.integrations.feishu.webhook import router as feishu_router
from docconv.integrations.feishu.webhook import configure as feishu_configure
from docconv.integrations.telegram.adapter import TelegramAdapter
from docconv.integrations.telegram.webhook import router as telegram_router
from docconv.integrations.telegram.webhook import configure as telegram_configure
from docconv.service.conversion_job_service import ConversionJobService
from docconv.service.job_status_callback import JobStatusCallback

logger = logging.getLogger(__name__)


def register_integration_routes(
    app: FastAPI,
    job_service: ConversionJobService,
    settings: BotIntegrationSettings | None = None,
) -> dict[str, Any]:
    """注册平台集成路由到 FastAPI 应用。

    Args:
        app: FastAPI 应用实例
        job_service: 转换任务服务
        settings: 机器人集成配置，不提供则从环境变量加载

    Returns:
        注册结果字典，包含注册的路由和状态
    """
    if settings is None:
        settings = BotIntegrationSettings.from_env()

    # 初始化依赖
    correlation_store = BotCorrelationStore()
    access_control = AccessControlMiddleware(
        max_jobs_per_minute=settings.rate_limit.jobs_per_minute,
    )

    # 创建 allowlist 集合
    telegram_allowed = set(settings.telegram.allowed_chats) if settings.telegram.allowed_chats else None
    feishu_allowed = set(settings.feishu.allowed_tenants) if settings.feishu.allowed_tenants else None

    # Telegram 适配器与路由
    telegram_adapter = None
    telegram_registered = False
    if settings.telegram.enabled and settings.telegram.bot_token:
        telegram_adapter = TelegramAdapter(
            bot_token=settings.telegram.bot_token,
            allowed_chats=telegram_allowed,
            webhook_secret=settings.telegram.webhook_secret,
        )

        telegram_configure(
            adapter=telegram_adapter,
            job_service=job_service,
            correlation_store=correlation_store,
            access_control=access_control,
            enabled=True,
        )
        app.include_router(telegram_router)
        telegram_registered = True
        logger.info("Telegram webhook 路由已注册")
    else:
        logger.info("Telegram 平台未启用，跳过路由注册")

    # 飞书适配器与路由
    feishu_adapter = None
    feishu_registered = False
    if settings.feishu.enabled and settings.feishu.app_id and settings.feishu.app_secret:
        feishu_adapter = FeishuAdapter(
            app_id=settings.feishu.app_id,
            app_secret=settings.feishu.app_secret,
            allowed_tenants=feishu_allowed,
            verification_token=settings.feishu.verification_token,
        )

        feishu_configure(
            adapter=feishu_adapter,
            job_service=job_service,
            correlation_store=correlation_store,
            access_control=access_control,
            enabled=True,
        )
        app.include_router(feishu_router)
        feishu_registered = True
        logger.info("飞书 webhook 路由已注册")
    else:
        logger.info("飞书平台未启用，跳过路由注册")

    # 注册终态回调钩子
    callback_handler = JobStatusCallback(
        correlation_store=correlation_store,
        job_service=job_service,
        telegram_adapter=telegram_adapter,
        feishu_adapter=feishu_adapter,
        send_report=settings.send_report,
    )

    # 存储到 app.state 供外部调用
    app.state.bot_callback_handler = callback_handler
    app.state.bot_correlation_store = correlation_store

    return {
        "telegram_registered": telegram_registered,
        "feishu_registered": feishu_registered,
        "routes": [
            r.path for r in app.routes
            if hasattr(r, "path") and "/integrations/" in getattr(r, "path", "")
        ],
        "send_report": settings.send_report,
    }
