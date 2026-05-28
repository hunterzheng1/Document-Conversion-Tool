"""Telegram Bot API httpx 客户端。

封装文件下载和消息发送，统一超时配置，token 脱敏日志。
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any

import httpx

from docconv.infra.bot_config import redact_secrets

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"

# 超时配置（秒）
SEND_TIMEOUT = 30
DOWNLOAD_TIMEOUT = 300

# 重试配置
MAX_RETRIES = 2
RETRY_DELAYS = [1, 3]  # 指数退避：1s, 3s


def _mask_token(token: str) -> str:
    """对 bot token 脱敏。"""
    if len(token) <= 8:
        return "***"
    return token[:4] + "***" + token[-4:]


class TelegramClient:
    """Telegram Bot API httpx 封装。

    职责：
    - 文件下载（getFile + 文件 URL 下载）
    - 消息发送（sendMessage、sendDocument）
    - 统一超时、重试
    - token 脱敏日志
    """

    def __init__(self, bot_token: str, base_url: str = TELEGRAM_API):
        self.bot_token = bot_token
        self.base_url = base_url
        self._send_client = httpx.AsyncClient(timeout=SEND_TIMEOUT)
        self._download_client = httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT)

    async def close(self) -> None:
        await self._send_client.aclose()
        await self._download_client.aclose()

    async def _post(self, method: str, **kwargs: Any) -> dict:
        """发送 POST 请求到 Telegram API。

        Args:
            method: API 方法名（如 sendMessage）
            **kwargs: 请求参数

        Returns:
            API 响应的 result 字段

        Raises:
            httpx.HTTPStatusError: HTTP 错误
        """
        url = f"{self.base_url}/bot{self.bot_token}/{method}"
        try:
            resp = await self._send_client.post(url, json=kwargs)
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                raise RuntimeError(f"Telegram API error: {data.get('description', 'unknown')}")
            return data.get("result", {})
        except httpx.HTTPStatusError as e:
            logger.error(
                "Telegram API HTTP error for %s: %s",
                method, _mask_token(self.bot_token),
            )
            raise
        except Exception as e:
            redacted = redact_secrets(str(e))
            logger.error("Telegram API error for %s: %s", method, redacted)
            raise

    async def send_message(
        self, chat_id: str, text: str, parse_mode: str = "Markdown",
    ) -> dict:
        """发送文本消息。

        Args:
            chat_id: 目标会话 ID
            text: 消息文本
            parse_mode: 解析模式，默认 Markdown

        Returns:
            API 响应结果
        """
        return await self._post(
            "sendMessage", chat_id=chat_id, text=text, parse_mode=parse_mode,
        )

    async def send_document(
        self, chat_id: str, document: str, caption: str = "",
    ) -> dict:
        """发送文档。

        Args:
            chat_id: 目标会话 ID
            document: 文件路径或 file_id
            caption: 文件说明

        Returns:
            API 响应结果
        """
        return await self._post(
            "sendDocument", chat_id=chat_id, document=document, caption=caption,
        )

    async def get_file_info(self, file_id: str) -> dict:
        """获取文件信息（file_path）。

        Args:
            file_id: Telegram 文件 ID

        Returns:
            包含 file_path 的字典
        """
        return await self._post("getFile", file_id=file_id)

    async def download_file(self, file_id: str, dest_path: str) -> str:
        """从 Telegram 下载文件到本地。

        流程：
        1. 调用 getFile 获取 file_path
        2. 从 Telegram file server 下载文件内容
        3. 保存到 dest_path

        Args:
            file_id: Telegram 文件 ID
            dest_path: 目标本地路径

        Returns:
            实际写入的本地文件路径

        Raises:
            RuntimeError: 下载失败
        """
        # 1. 获取 file_path
        file_info = await self.get_file_info(file_id)
        file_path = file_info.get("file_path")
        if not file_path:
            raise RuntimeError(f"Telegram getFile 未返回 file_path: {file_info}")

        # 2. 下载文件内容（带重试）
        url = f"{self.base_url}/file/bot{self.bot_token}/{file_path}"
        content = await self._download_with_retry(url)

        # 3. 写入本地
        dest = Path(dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        logger.info("Telegram 文件已下载: %s (%d bytes)", dest.name, len(content))
        return str(dest)

    async def _download_with_retry(self, url: str) -> bytes:
        """下载文件内容，支持重试。

        Args:
            url: 文件下载 URL

        Returns:
            文件内容字节

        Raises:
            RuntimeError: 所有重试均失败
        """
        last_error = None
        for attempt, delay in enumerate([0] + RETRY_DELAYS):
            if attempt > 0:
                logger.info("Telegram 下载重试 %d/%d, 等待 %ds", attempt, MAX_RETRIES, delay)
                await asyncio.sleep(delay)
            try:
                resp = await self._download_client.get(url)
                resp.raise_for_status()
                return resp.content
            except Exception as e:
                last_error = e
        raise RuntimeError(f"Telegram 文件下载失败（重试 {MAX_RETRIES} 次后）: {redact_secrets(str(last_error))}")

    async def send_message_with_retry(
        self, chat_id: str, text: str, parse_mode: str = "Markdown",
    ) -> dict:
        """发送消息，支持重试。

        Args:
            chat_id: 目标会话 ID
            text: 消息文本
            parse_mode: 解析模式

        Returns:
            API 响应结果
        """
        last_error = None
        for attempt, delay in enumerate([0] + RETRY_DELAYS):
            if attempt > 0:
                logger.info("消息发送重试 %d/%d, 等待 %ds", attempt, MAX_RETRIES, delay)
                await asyncio.sleep(delay)
            try:
                return await self.send_message(chat_id, text, parse_mode)
            except Exception as e:
                last_error = e
        raise RuntimeError(f"消息发送失败（重试 {MAX_RETRIES} 次后）: {redact_secrets(str(last_error))}")
