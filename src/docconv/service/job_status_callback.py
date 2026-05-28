"""Job 终态回调机制。

当转换任务达到终态（成功/失败）时，通过 bot_correlations 查询关联的平台信息，
调用对应平台的 adapter 发送结果。
"""

from __future__ import annotations

import logging
from typing import Any

from docconv.infra.bot_correlation_store import BotCorrelationStore
from docconv.infra.bot_error_codes import (
    AuditEvent,
    log_audit,
)
from docconv.integrations.common import BotJobCorrelation, BotPlatform
from docconv.integrations.feishu.adapter import FeishuAdapter
from docconv.integrations.telegram.adapter import TelegramAdapter
from docconv.service.conversion_job_service import ConversionJobService

logger = logging.getLogger(__name__)


class JobStatusCallback:
    """Job 终态回调处理器。

    职责：
    - 当 job 达到终态时，查询 bot_correlations 获取平台回传信息
    - 成功 job 发送 Markdown 结果或报告
    - 失败 job 发送脱敏失败摘要
    - 回传失败时保留 job 终态，仅记录日志
    """

    def __init__(
        self,
        correlation_store: BotCorrelationStore,
        job_service: ConversionJobService,
        telegram_adapter: TelegramAdapter | None = None,
        feishu_adapter: FeishuAdapter | None = None,
        send_report: bool = True,
    ):
        self.correlation_store = correlation_store
        self.job_service = job_service
        self.telegram_adapter = telegram_adapter
        self.feishu_adapter = feishu_adapter
        self.send_report = send_report

    async def handle_terminal_state(self, job_id: str) -> None:
        """处理达到终态的 job。

        Args:
            job_id: 任务 ID
        """
        try:
            job = self.job_service.get_job(job_id)
        except Exception as e:
            logger.error("获取 job %s 失败: %s", job_id, str(e)[:200])
            return

        # 查询关联的平台信息
        correlations = self.correlation_store.get_by_job_id(job_id)
        if not correlations:
            logger.debug("job %s 无平台关联，跳过回传", job_id)
            return

        for corr in correlations:
            try:
                if job.status == "succeeded":
                    await self._send_success(corr, job)
                elif job.status in ("failed", "cancelled"):
                    await self._send_failure(corr, job)
            except Exception as e:
                logger.error(
                    "回传结果失败 (correlation=%s, job=%s): %s",
                    corr.id, job_id, str(e)[:200],
                )
                # 回传失败不影响 job 终态

    async def _send_success(self, corr: BotJobCorrelation, job: Any) -> None:
        """发送成功结果。

        Args:
            corr: 关联记录
            job: JobRecord
        """
        adapter = self._get_adapter(corr.platform)
        if not adapter:
            logger.warning("未找到平台 %s 的适配器", corr.platform)
            return

        # 构建结果消息
        result_text = f"转换完成！\n\n"
        result_text += f"任务: {job.job_id[-8:]}\n"
        result_text += f"文件: {job.original_filename}\n"

        # 如果需要发送报告
        if self.send_report and job.output_path:
            try:
                from pathlib import Path
                output = Path(job.output_path)
                if output.exists():
                    result_text += "\n结果已生成。"
                    await adapter.send_result(
                        corr.chat_id,
                        result_text,
                        file_path=job.output_path,
                    )
                    log_audit(AuditEvent(
                        platform=corr.platform,
                        chat_hash=corr.chat_id[:8],
                        job_id=job.job_id,
                        event_type="callback_sent",
                    ))
                    return
            except Exception:
                pass

        # 否则发送 Markdown 摘要
        try:
            if job.output_path:
                from pathlib import Path
                output = Path(job.output_path)
                if output.exists():
                    content = output.read_text(encoding="utf-8")
                    # 截取前 2000 字符
                    preview = content[:2000]
                    if len(content) > 2000:
                        preview += "\n\n...（内容过长，请查看完整文件）"
                    result_text += preview
        except Exception:
            result_text += "结果文件生成完毕。"

        await adapter.send_result(corr.chat_id, result_text)
        log_audit(AuditEvent(
            platform=corr.platform,
            chat_hash=corr.chat_id[:8],
            job_id=job.job_id,
            event_type="callback_sent",
        ))

    async def _send_failure(self, corr: BotJobCorrelation, job: Any) -> None:
        """发送失败摘要（脱敏后）。

        Args:
            corr: 关联记录
            job: JobRecord
        """
        adapter = self._get_adapter(corr.platform)
        if not adapter:
            logger.warning("未找到平台 %s 的适配器", corr.platform)
            return

        error_summary = job.error_message or "未知错误"
        # 截断到合理长度
        if len(error_summary) > 500:
            error_summary = error_summary[:500] + "..."

        await adapter.send_failure(corr.chat_id, job.job_id, error_summary)
        log_audit(AuditEvent(
            platform=corr.platform,
            chat_hash=corr.chat_id[:8],
            job_id=job.job_id,
            event_type="callback_sent",
            error_type=job.error_type,
        ))

    def _get_adapter(self, platform: str):
        """根据平台返回对应的 adapter。"""
        if platform == BotPlatform.TELEGRAM.value:
            return self.telegram_adapter
        elif platform == BotPlatform.FEISHU.value:
            return self.feishu_adapter
        logger.warning("未知平台: %s", platform)
        return None
