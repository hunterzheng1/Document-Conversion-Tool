"""飞书适配器（FeishuAdapter）。

实现 BotAdapter 抽象基类，整合 FeishuClient 和 InstructionParser。
负责：验证飞书事件（challenge 验证、签名校验）、allowlist 检查、
解析飞书事件为 BotMessage、文件下载、指令解析。
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

from docconv.infra.access_control import AllowlistChecker
from docconv.infra.bot_error_codes import BotErrorCodes
from docconv.integrations.common import BotAdapter, BotMessage, BotPlatform
from docconv.integrations.feishu.client import FeishuClient
from docconv.service.instruction_parser import InstructionParser, ParsedInstruction

logger = logging.getLogger(__name__)


class FeishuAdapter(BotAdapter):
    """飞书 Bot 适配器实现。"""

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        allowed_tenants: set[str] | None = None,
        verification_token: str = "",
        encrypt_key: str = "",
        storage_root: str = ".data/docconv",
    ):
        self.client = FeishuClient(app_id, app_secret)
        self.allowlist = AllowlistChecker(allowed_tenants)
        self.verification_token = verification_token
        self.encrypt_key = encrypt_key
        self.storage_root = storage_root
        self.instruction_parser = InstructionParser()

    def verify_source(self, payload: dict) -> bool:
        """验证飞书事件来源。

        支持两种场景：
        1. challenge 验证事件（URL 配置阶段）
        2. 消息事件签名校验

        Args:
            payload: 飞书事件载荷

        Returns:
            True 表示来源合法
        """
        # 1. challenge 验证事件
        if payload.get("type") == "url_verification":
            token = payload.get("token", "")
            return token == self.verification_token

        # 2. 消息事件校验
        if self.verification_token:
            event_token = payload.get("header", {}).get("token", "")
            if event_token != self.verification_token:
                logger.warning("飞书事件 token 不匹配")
                return False

        # 如果有 encrypt_key，校验签名
        if self.encrypt_key:
            timestamp = str(payload.get("header", {}).get("timestamp", ""))
            nonce = payload.get("header", {}).get("nonce", "")
            expected_sign = self._compute_signature(timestamp, nonce, self.encrypt_key)
            actual_sign = payload.get("header", {}).get("encrypt", "")
            if actual_sign and actual_sign != expected_sign:
                logger.warning("飞书事件签名不匹配")
                return False

        return True

    def _compute_signature(self, timestamp: str, nonce: str, key: str) -> str:
        """计算飞书事件签名。"""
        content = timestamp + nonce + key
        return hashlib.sha256(content.encode()).hexdigest()

    def check_allowlist(self, tenant_or_user: str) -> tuple[bool, str]:
        """检查租户/用户是否在 allowlist 中。

        Args:
            tenant_or_user: 租户或用户标识

        Returns:
            (是否允许, 拒绝原因)
        """
        result = self.allowlist.check(tenant_or_user)
        return result.allowed, result.reason

    def parse_message(self, payload: dict) -> BotMessage:
        """将飞书事件解析为 BotMessage。

        Args:
            payload: 飞书事件载荷

        Returns:
            BotMessage 实例

        Raises:
            ValueError: 事件格式非法
        """
        event = payload.get("event", {})
        message_data = event.get("message", {})
        sender = event.get("sender", {})

        chat_id = message_data.get("chat_id", "")
        sender_id = sender.get("sender_id", {}).get("open_id", "") or ""
        msg_type = message_data.get("message_type", "")
        message_id = message_data.get("message_id", "")

        # 解析消息内容
        text = ""
        file_id = ""
        filename = ""

        content_str = message_data.get("content", "{}")
        import json
        try:
            content_obj = json.loads(content_str) if isinstance(content_str, str) else content_str
        except json.JSONDecodeError:
            content_obj = {}

        if msg_type == "text":
            text = content_obj.get("text", "")
        elif msg_type == "file":
            file_id = content_obj.get("file_key", "")
            filename = content_obj.get("file_name", "unknown.pdf")
            text = "/convert"
        elif msg_type == "image":
            file_id = content_obj.get("image_key", "")
            filename = "image.png"

        if not chat_id:
            raise ValueError("飞书事件中无 chat_id")

        return BotMessage(
            platform=BotPlatform.FEISHU.value,
            external_message_id=message_id,
            chat_id=chat_id,
            sender_id=sender_id,
            file_id=file_id,
            filename=filename,
            instruction=text,
            platform_meta=payload,
        )

    def handle_challenge(self, payload: dict) -> dict:
        """处理飞书 challenge 验证事件。

        Args:
            payload: 飞书事件载荷

        Returns:
            应答字典，包含 challenge 值
        """
        challenge = payload.get("challenge", "")
        return {"challenge": challenge}

    def check_file_type(self, filename: str) -> tuple[bool, str]:
        """检查文件类型是否为 PDF。

        Args:
            filename: 文件名

        Returns:
            (是否支持, 错误原因)
        """
        if not filename:
            return False, "文件名为空"
        if not filename.lower().endswith(".pdf"):
            return False, f"不支持的文件类型: {filename}（仅支持 PDF）"
        return True, ""

    async def download_file(self, file_id: str, dest_path: str) -> str:
        """从飞书下载文件。

        Args:
            file_id: 飞书文件 key
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
            await self.client.send_file(chat_id, file_path)
        else:
            await self.client.send_text(chat_id, result_text)

    async def send_failure(self, chat_id: str, job_id: str, error_summary: str) -> None:
        """发送脱敏失败摘要。

        Args:
            chat_id: 目标会话 ID
            job_id: 关联任务 ID
            error_summary: 脱敏后的失败摘要
        """
        short_id = job_id[-8:] if len(job_id) > 8 else job_id
        text = f"任务 {short_id} 转换失败：{error_summary}"
        await self.client.send_text(chat_id, text)

    async def send_text(self, chat_id: str, text: str) -> None:
        """发送纯文本消息。"""
        await self.client.send_text(chat_id, text)

    def parse_instruction(self, text: str) -> ParsedInstruction:
        """解析用户指令。"""
        return self.instruction_parser.parse(text)

    async def close(self) -> None:
        """关闭底层 HTTP 客户端。"""
        await self.client.close()
