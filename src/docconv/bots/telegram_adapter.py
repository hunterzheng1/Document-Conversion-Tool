"""Telegram Bot 适配器。"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

import httpx

from docconv.bots.base import BotAdapter, BotMessage
from docconv.infra.logger import setup_logger

logger = setup_logger(__name__)

TELEGRAM_API = "https://api.telegram.org"

# 支持的指令
COMMANDS = {
    "/convert": "上传 PDF 文件开始转换",
    "/status": "查看当前任务状态",
    "/cancel": "取消当前任务",
    "/help": "显示帮助信息",
}

# 结果消息最大长度（Telegram 单条 4096 字符）
MAX_TEXT_LENGTH = 4000


class TelegramClient:
    """Telegram Bot API httpx 封装。"""

    def __init__(self, bot_token: str, base_url: str = TELEGRAM_API):
        self.bot_token = bot_token
        self.base_url = base_url
        self._client = httpx.AsyncClient(timeout=30.0)

    async def _post(self, method: str, **kwargs: Any) -> dict:
        url = f"{self.base_url}/bot{self.bot_token}/{method}"
        resp = await self._client.post(url, json=kwargs)
        resp.raise_for_status()
        return resp.json()

    async def send_message(self, chat_id: str, text: str, parse_mode: str = "Markdown") -> dict:
        return await self._post("sendMessage", chat_id=chat_id, text=text, parse_mode=parse_mode)

    async def send_document(self, chat_id: str, document: str, caption: str = "") -> dict:
        return await self._post("sendDocument", chat_id=chat_id, document=document, caption=caption)

    async def download_file(self, file_path: str) -> bytes:
        # 先从 getFile 获取 file_path
        url = f"{self.base_url}/file/bot{self.bot_token}/{file_path}"
        resp = await self._client.get(url)
        resp.raise_for_status()
        return resp.content

    async def get_file_info(self, file_id: str) -> dict:
        result = await self._post("getFile", file_id=file_id)
        return result.get("result", {})

    async def close(self):
        await self._client.aclose()


class TelegramAdapter(BotAdapter):
    """Telegram Bot 适配器实现。"""

    def __init__(
        self,
        bot_token: str,
        job_service: Any,
        storage_root: str = ".data/docconv",
        poll_timeout: int = 30,
    ):
        self.bot_token = bot_token
        self.client = TelegramClient(bot_token)
        self.job_service = job_service
        self.storage_root = storage_root
        self.poll_timeout = poll_timeout
        self._running = False
        self._offset = 0
        # user_id -> job_id 映射
        self._user_jobs: dict[str, str] = {}

    async def handle_message(self, message: BotMessage) -> None:
        """处理 Telegram 消息。"""
        text = message.text.strip()
        chat_id = message.chat_id

        if text == "/help" or text == "/start":
            help_text = "docconv Bot 用法：\n\n"
            help_text += "\n".join(f"`{cmd}` - {desc}" for cmd, desc in COMMANDS.items())
            await self.send_text(chat_id, help_text)
            return

        if text == "/status":
            job_id = self._user_jobs.get(message.user_id)
            if not job_id:
                await self.send_text(chat_id, "暂无转换任务。请先发送 /convert 并上传 PDF。")
                return
            await self._send_job_status(chat_id, job_id)
            return

        if text == "/cancel":
            job_id = self._user_jobs.get(message.user_id)
            if not job_id:
                await self.send_text(chat_id, "暂无可取消的任务。")
                return
            try:
                self.job_service.cancel_job(job_id)
                await self.send_text(chat_id, f"任务 `{job_id[-8:]}` 已取消。")
                del self._user_jobs[message.user_id]
            except Exception as e:
                await self.send_error(chat_id, str(e))
            return

        # 如果是 /convert 或无文本但携带文件
        if message.file_url:
            await self._process_file(chat_id, message.user_id, message)
            return

        if text == "/convert":
            await self.send_text(chat_id, "请发送要转换的 PDF 文件。")
            return

        # 未知指令
        await self.send_text(chat_id, "未知指令。发送 /help 查看可用命令。")

    async def send_text(self, chat_id: str, text: str) -> None:
        try:
            # 截断超长消息
            if len(text) > MAX_TEXT_LENGTH:
                text = text[:MAX_TEXT_LENGTH] + "\n\n...（内容过长，请下载 Markdown 文件查看完整结果）"
            await self.client.send_message(chat_id, text)
        except Exception as e:
            _log_bot_error("telegram", "send_message", e)

    async def send_file(self, chat_id: str, file_path: str, caption: str = "") -> None:
        try:
            await self.client.send_document(chat_id, file_path, caption=caption)
        except Exception as e:
            _log_bot_error("telegram", "send_file", e)
            await self.send_text(chat_id, "结果文件发送失败")

    async def send_error(self, chat_id: str, error_message: str) -> None:
        # 脱敏处理
        safe_msg = _redact_secrets(error_message)
        await self.send_text(chat_id, f"错误: {safe_msg}")

    async def start_polling(self) -> None:
        """使用 getUpdates 轮询消息。"""
        self._running = True
        await self.send_text("self", "Bot 已启动。")  # 通知自身（需替换为 admin chat_id）
        logger.info("Telegram Bot 开始轮询...")

        while self._running:
            try:
                result = await self.client._post(
                    "getUpdates",
                    offset=self._offset,
                    timeout=self.poll_timeout,
                )
                for update in result.get("result", []):
                    self._offset = update["update_id"] + 1
                    msg = update.get("message")
                    if not msg:
                        continue
                    chat_id = str(msg["chat"]["id"])
                    user_id = str(msg["from"]["id"])
                    text = msg.get("text", "")
                    file_url = ""
                    file_name = ""

                    # 检查文档附件
                    if doc := msg.get("document"):
                        file_id = doc["file_id"]
                        file_name = doc.get("file_name", "unknown.pdf")
                        file_info = await self.client.get_file_info(file_id)
                        file_url = file_info.get("file_path", "")

                    bot_message = BotMessage(
                        platform="telegram",
                        user_id=user_id,
                        chat_id=chat_id,
                        text=text,
                        file_url=file_url,
                        file_name=file_name,
                    )
                    await self.handle_message(bot_message)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Telegram polling error: %s", e)
                await asyncio.sleep(5)

    async def stop_polling(self) -> None:
        self._running = False
        await self.client.close()
        logger.info("Telegram Bot 已停止。")

    # ---- 内部方法 ----

    async def _process_file(self, chat_id: str, user_id: str, message: BotMessage) -> None:
        """下载文件并提交转换任务。"""
        await self.send_text(chat_id, "正在处理文件，请稍候...")

        try:
            # 下载文件到本地 workspace
            if message.file_url:
                file_content = await self.client.download_file(message.file_url)
            else:
                await self.send_error(chat_id, "文件下载失败")
                return

            tmp_dir = Path(self.storage_root) / "bots" / "telegram" / user_id
            tmp_dir.mkdir(parents=True, exist_ok=True)
            local_path = tmp_dir / message.file_name

            with open(local_path, "wb") as f:
                f.write(file_content)

            # 创建转换任务
            from docconv.service.conversion_job_service import ConversionJobService
            job = self.job_service.create_job_from_file(
                source="telegram",
                input_file_path=str(local_path),
                original_filename=message.file_name,
                instruction=message.text.lstrip("/convert").strip(),
                options={},
            )
            self._user_jobs[user_id] = job.job_id
            await self.send_text(chat_id, f"任务已创建: `{job.job_id[-8:]}`\n开始转换，使用 /status 查看进度。")

        except Exception as e:
            _log_bot_error("telegram", "file_processing", e)
            await self.send_error(chat_id, str(e))

    async def _send_job_status(self, chat_id: str, job_id: str) -> None:
        """回传任务状态。"""
        try:
            job = self.job_service.get_job(job_id)
            if not job:
                await self.send_text(chat_id, f"任务 `{job_id[-8:]}` 不存在。")
                return

            status = job.status
            status_msg = f"任务 `{job_id[-8:]}`: {status}"
            if job.progress_json:
                pct = job.progress_json.get("progress_percent", 0)
                status_msg += f"\n进度: {pct}%"
            if job.error_message:
                status_msg += f"\n错误: {_redact_secrets(job.error_message)}"

            await self.send_text(chat_id, status_msg)

            if job.status == "succeeded" and job.output_path:
                await self.send_file(chat_id, job.output_path, caption="转换完成！")

        except Exception as e:
            await self.send_error(chat_id, str(e))


def _redact_secrets(text: str) -> str:
    """简单脱敏。"""
    import re
    # 替换 URL 中的 token 部分
    text = re.sub(r'(token=|key=|api_key=)\S+', r'\1***', text, flags=re.IGNORECASE)
    # 替换 Bearer token
    text = re.sub(r'Bearer \S+', 'Bearer ***', text)
    return text


def _log_bot_error(platform: str, operation: str, error: Exception) -> None:
    """记录 Bot 平台故障的结构化日志（含脱敏）。"""
    import uuid
    correlation_id = str(uuid.uuid4())[:8]
    logger.error(
        "Bot error: platform=%s, operation=%s, correlation_id=%s, error_type=%s, error=%s",
        platform,
        operation,
        correlation_id,
        type(error).__name__,
        _redact_secrets(str(error)),
    )
