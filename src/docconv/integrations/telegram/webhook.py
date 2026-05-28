"""Telegram Webhook 端点。

FastAPI APIRouter，注册 POST /integrations/telegram/webhook 端点。
接收 Telegram update，调用 TelegramAdapter 处理流程。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from docconv.infra.access_control import AccessControlMiddleware
from docconv.infra.bot_correlation_store import BotCorrelationStore
from docconv.infra.bot_error_codes import (
    AuditEvent,
    AuditTimer,
    BotErrorCodes,
    BotErrorResponse,
    log_audit,
)
from docconv.integrations.common import BotJobCorrelation
from docconv.integrations.telegram.adapter import TelegramAdapter
from docconv.service.conversion_job_service import ConversionJobService
from docconv.service.job_models import ConversionRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations/telegram", tags=["telegram"])

# 全局依赖（由应用启动时注入）
_telegram_adapter: TelegramAdapter | None = None
_job_service: ConversionJobService | None = None
_correlation_store: BotCorrelationStore | None = None
_access_control: AccessControlMiddleware | None = None
_telegram_enabled: bool = False


def configure(
    adapter: TelegramAdapter,
    job_service: ConversionJobService,
    correlation_store: BotCorrelationStore,
    access_control: AccessControlMiddleware,
    enabled: bool = False,
) -> None:
    """配置路由器依赖。

    Args:
        adapter: Telegram 适配器
        job_service: 转换任务服务
        correlation_store: 关联存储
        access_control: 访问控制中间件
        enabled: 是否启用 Telegram 平台
    """
    global _telegram_adapter, _job_service, _correlation_store
    global _access_control, _telegram_enabled
    _telegram_adapter = adapter
    _job_service = job_service
    _correlation_store = correlation_store
    _access_control = access_control
    _telegram_enabled = enabled


@router.post("/webhook")
async def telegram_webhook(request: Request) -> dict[str, Any]:
    """接收 Telegram update 并处理。

    流程：
    1. 检查平台是否启用
    2. 验证来源
    3. 解析消息
    4. allowlist + 速率限制检查
    5. 下载 PDF
    6. 创建转换任务
    7. 创建关联记录
    8. 返回受理消息
    """
    # 1. 检查启用
    if not _telegram_enabled:
        raise HTTPException(status_code=503, detail="Telegram 平台未启用")

    if not _telegram_adapter or not _job_service or not _correlation_store:
        raise HTTPException(status_code=503, detail="Telegram 服务未初始化")

    # 2. 解析请求体
    body = await request.json()
    audit = AuditEvent(platform="telegram", event_type="received")

    with AuditTimer(audit):
        # 3. 验证来源
        if not _telegram_adapter.verify_source(body):
            audit.error_code = BotErrorCodes.AUTH_WEBHOOK_FAILED
            log_audit(audit)
            raise HTTPException(status_code=401, detail="Webhook 验证失败")

        # 4. 解析消息
        try:
            bot_message = _telegram_adapter.parse_message(body)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        audit.chat_id = bot_message.chat_id[:8]  # 截断
        audit.event_type = "message_parsed"

        # 5. allowlist 检查
        allowed, reason = _telegram_adapter.check_allowlist(bot_message.chat_id)
        if not allowed:
            audit.error_code = BotErrorCodes.AUTH_UNAUTHORIZED
            log_audit(audit)
            raise HTTPException(status_code=403, detail=reason)

        # 6. 速率限制
        if _access_control:
            rate_result = _access_control.check_access(bot_message.chat_id)
            if not rate_result.allowed:
                audit.error_code = "429"
                log_audit(audit)
                raise HTTPException(
                    status_code=429,
                    detail=rate_result.reason,
                )

        # 7. 有文件才创建任务
        if bot_message.file_id:
            audit.event_type = "downloading"

            # 检查文件类型
            is_pdf, _ = _telegram_adapter.check_file_type(bot_message.filename) if hasattr(_telegram_adapter, 'check_file_type') else (True, "")
            if bot_message.filename and not is_pdf:
                raise HTTPException(
                    status_code=400,
                    detail=f"不支持的文件类型: {bot_message.filename}",
                )

            try:
                # 下载文件
                workspace = Path(".data/docconv") / "bots" / "telegram" / bot_message.chat_id
                workspace.mkdir(parents=True, exist_ok=True)
                local_path = workspace / (bot_message.filename or "unknown.pdf")
                await _telegram_adapter.download_file(bot_message.file_id, str(local_path))

                audit.event_type = "downloaded"

                # 解析指令
                parsed = _telegram_adapter.parse_instruction(bot_message.instruction)
                if parsed.rejected:
                    raise HTTPException(status_code=400, detail=parsed.reject_reason)

                # 创建转换任务
                conv_request = ConversionRequest(
                    source="telegram",
                    input_file_path=str(local_path),
                    original_filename=bot_message.filename or "unknown.pdf",
                    instruction=bot_message.instruction,
                    options=parsed.options,
                )
                job_result = _job_service.create_job(conv_request)
                job_id = job_result["job_id"]

                bot_message.job_id = job_id
                audit.job_id = job_id
                audit.event_type = "job_created"

                # 创建关联记录
                correlation = BotJobCorrelation(
                    job_id=job_id,
                    platform=bot_message.platform,
                    external_message_id=bot_message.external_message_id,
                    chat_id=bot_message.chat_id,
                    sender_id=bot_message.sender_id,
                )
                _correlation_store.create_correlation(correlation)

                # 发送受理消息
                await _telegram_adapter.send_text(
                    bot_message.chat_id,
                    f"任务已创建: `{job_id[-8:]}`\n开始转换，使用 /status 查看进度。",
                )

            except HTTPException:
                raise
            except Exception as e:
                logger.error("Telegram webhook processing error: %s", str(e)[:200])
                audit.error_type = str(e)[:200]
                audit.error_code = BotErrorCodes.DOWNLOAD_FAILED
                raise HTTPException(status_code=500, detail="处理失败")

        log_audit(audit)

        return {"ok": True}
