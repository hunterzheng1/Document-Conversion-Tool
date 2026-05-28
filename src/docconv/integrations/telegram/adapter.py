"""Telegram 适配器（TelegramAdapter）。

实现 BotAdapter 抽象基类，整合 TelegramClient 和 InstructionParser。
负责：验证 webhook 来源、allowlist 检查、解析事件为 BotMessage、
文件下载、指令解析。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from docconv.infra.access_control import AllowlistChecker
from docconv.integrations.common import BotAdapter, BotMessage, BotJobCorrelation, BotPlatform
from docconv.integrations.telegram.client import TelegramClient
from docconv.service.instruction_parser import InstructionParser, ParsedInstruction

logger = logging.getLogger(__name__)


class TelegramAdapter(BotAdapter):
    """Telegram Bot 适配器实现。"""

    def __init__(
        self,
        bot_token: str,
        allowed_chats: set[str] | None = None,
        webhook_secret: str = "",
        storage_root: str = ".data/docconv",
    ):
        self.client = TelegramClient(bot_token)
        self.allowlist = AllowlistChecker(allowed_chats)
        self.webhook_secret = webhook_secret
        self.storage_root = storage_root
        self.instruction_parser = InstructionParser()

    def verify_source(self, payload: dict) -> bool:
        """验证 webhook 来源。

        校验 webhook secret token。

        Args:
            payload: Telegram update 事件载荷

        Returns:
            True 表示来源合法
        """
        # Telegram webhook 验证：检查 secret token
        # 在 setWebhook 时配置的 secret_token 会在 header 中发送
        # 这里简化处理，检查 payload 中的 secret_token
        if self.webhook_secret:
            secret = payload.get("secret_token", "")
            return secret == self.webhook_secret
        return True

    def check_allowlist(self, chat_id: str) -> tuple[bool, str]:
        """检查 chat_id 是否在 allowlist 中。

        Args:
            chat_id: 会话 ID

        Returns:
            (是否允许, 拒绝原因)
        """
        result = self.allowlist.check(chat_id)
        return result.allowed, result.reason

    def parse_message(self, payload: dict) -> BotMessage:
        """将 Telegram update 事件解析为 BotMessage。

        Args:
            payload: Telegram update 事件

        Returns:
            BotMessage 实例

        Raises:
            ValueError: 事件格式非法
        """
        msg = payload.get("message")
        if not msg:
            raise ValueError("Telegram update 中无 message 字段")

        chat_id = str(msg.get("chat", {}).get("id", ""))
        sender_id = str(msg.get("from", {}).get("id", ""))
        text = msg.get("text", "") or msg.get("caption", "") or ""

        # 检查文档附件
        file_id = ""
        filename = ""
        if doc := msg.get("document"):
            file_id = doc.get("file_id", "")
            filename = doc.get("file_name", "unknown.pdf")
        elif photo_list := msg.get("photo"):
            # 取最大尺寸的照片
            photo = max(photo_list, key=lambda p: p.get("file_size", 0))
            file_id = photo.get("file_id", "")
            filename = "photo.jpg"

        if not chat_id:
            raise ValueError("Telegram message 中无 chat.id")

        return BotMessage(
            platform=BotPlatform.TELEGRAM.value,
            external_message_id=str(payload.get("update_id", "")),
            chat_id=chat_id,
            sender_id=sender_id,
            file_id=file_id,
            filename=filename,
            instruction=text,
            platform_meta=payload,
        )

    async def download_file(self, file_id: str, dest_path: str) -> str:
        """从 Telegram 下载文件。

        Args:
            file_id: Telegram 文件 ID
            dest_path: 目标本地路径

        Returns:
            实际写入的本地文件路径
        """
        return await self.client.download_file(file_id, dest_path)

    async def send_result(self, chat_id: str, result_text: str, file_path: str = "") -> None:
        """发送转换结果。

        Args:
            chat_id: 目标会话 ID
            result_text: Markdown 结果文本
            file_path: 结果文件路径（可选）
        """
        if file_path:
            await self.client.send_document(chat_id, file_path, caption="转换完成！")
        else:
            await self.client.send_message(chat_id, result_text)

    async def send_failure(self, chat_id: str, job_id: str, error_summary: str) -> None:
        """发送脱敏失败摘要。

        Args:
            chat_id: 目标会话 ID
            job_id: 关联任务 ID
            error_summary: 脱敏后的失败摘要
        """
        short_id = job_id[-8:] if len(job_id) > 8 else job_id
        text = f"任务 {short_id} 转换失败：{error_summary}"
        await self.client.send_message(chat_id, text)

    async def send_text(self, chat_id: str, text: str) -> None:
        """发送纯文本消息。"""
        await self.client.send_message(chat_id, text)

    def parse_instruction(self, text: str) -> ParsedInstruction:
        """解析用户指令。

        Args:
            text: 用户输入文本

        Returns:
            解析结果
        """
        return self.instruction_parser.parse(text)

    async def close(self) -> None:
        """关闭底层 HTTP 客户端。"""
        await self.client.close()
