"""飞书（Feishu/Lark）Bot 适配器。"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
from typing import Any

import httpx

from docconv.bots.base import BotAdapter, BotMessage
from docconv.infra.logger import setup_logger

logger = setup_logger(__name__)

FEISHU_HOST = "https://open.feishu.cn"
MAX_TEXT_LENGTH = 1500  # 飞书单条消息限制


class FeishuClient:
    """飞书 Open API httpx 封装。"""

    def __init__(self, app_id: str, app_secret: str, base_url: str = FEISHU_HOST):
        self.app_id = app_id
        self.app_secret = app_secret
        self.base_url = base_url
        self._client = httpx.AsyncClient(timeout=30.0, base_url=base_url)
        self._tenant_token = ""

    async def _ensure_token(self) -> None:
        if self._tenant_token:
            return
        resp = await self._client.post(
            "/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": self.app_id, "app_secret": self.app_secret},
        )
        resp.raise_for_status()
        data = resp.json()
        self._tenant_token = data.get("tenant_access_token", "")

    async def _post(self, api_path: str, **kwargs: Any) -> dict:
        await self._ensure_token()
        headers = {"Authorization": f"Bearer {self._tenant_token}"}
        url = f"{self.base_url}{api_path}"
        resp = await self._client.post(url, headers=headers, json=kwargs.get("json", {}))
        resp.raise_for_status()
        return resp.json()

    async def send_text(self, chat_id: str, text: str) -> dict:
        return await self._post(
            "/open-apis/im/v1/messages",
            json={
                "receive_id_type": "chat_id",
                "msg_type": "text",
                "content": '{"text": "' + text.replace('"', '\\"') + '"}',
            },
            params={"receive_id": chat_id},
        )

    async def send_image(self, chat_id: str, image_key: str) -> dict:
        return await self._post(
            "/open-apis/im/v1/messages",
            json={
                "receive_id_type": "chat_id",
                "msg_type": "image",
                "content": '{"image_key": "' + image_key + '"}',
            },
            params={"receive_id": chat_id},
        )

    async def download_file(self, file_key: str) -> bytes:
        await self._ensure_token()
        headers = {"Authorization": f"Bearer {self._tenant_token}"}
        resp = await self._client.get(
            f"{self.base_url}/open-apis/im/v1/files/{file_key}",
            headers=headers,
        )
        resp.raise_for_status()
        return resp.content

    async def close(self):
        await self._client.aclose()


class FeishuAdapter(BotAdapter):
    """飞书 Bot 适配器实现。"""

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        job_service: Any,
        storage_root: str = ".data/docconv",
        verification_token: str = "",
    ):
        self.app_id = app_id
        self.app_secret = app_secret
        self.client = FeishuClient(app_id, app_secret)
        self.job_service = job_service
        self.storage_root = storage_root
        self.verification_token = verification_token
        self._running = False
        self._user_jobs: dict[str, str] = {}

    async def handle_message(self, message: BotMessage) -> None:
        text = message.text.strip()
        chat_id = message.chat_id

        if text in ("/help", "/start"):
            await self.send_text(chat_id, "docconv Bot：发送 /convert 并上传 PDF 开始转换，/status 查看进度，/cancel 取消任务。")
            return

        if text == "/status":
            job_id = self._user_jobs.get(message.user_id)
            if not job_id:
                await self.send_text(chat_id, "暂无转换任务。")
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
                await self.send_text(chat_id, f"任务 {job_id[-8:]} 已取消。")
                del self._user_jobs[message.user_id]
            except Exception as e:
                await self.send_error(chat_id, str(e))
            return

        if message.file_url:
            await self._process_file(chat_id, message.user_id, message)
            return

        if text == "/convert":
            await self.send_text(chat_id, "请发送要转换的 PDF 文件。")
            return

        await self.send_text(chat_id, "未知指令。发送 /help 查看可用命令。")

    async def send_text(self, chat_id: str, text: str) -> None:
        try:
            if len(text) > MAX_TEXT_LENGTH:
                text = text[:MAX_TEXT_LENGTH] + "\n\n...（内容过长，请下载 Markdown 文件）"
            await self.client.send_text(chat_id, text)
        except Exception as e:
            _log_bot_error("feishu", "send_message", e)

    async def send_file(self, chat_id: str, file_path: str, caption: str = "") -> None:
        await self.send_text(chat_id, f"转换完成，文件路径: {file_path}\n{caption}")

    async def send_error(self, chat_id: str, error_message: str) -> None:
        safe_msg = _redact_secrets(error_message)
        await self.send_text(chat_id, f"错误: {safe_msg}")

    async def start_polling(self) -> None:
        """飞书推荐使用 Webhook，此处提供简易轮询兼容实现。"""
        self._running = True
        logger.info("Feishu Bot 已启动。")
        while self._running:
            await asyncio.sleep(5)

    async def stop_polling(self) -> None:
        self._running = False
        await self.client.close()
        logger.info("Feishu Bot 已停止。")

    async def handle_webhook(self, payload: dict) -> dict:
        """处理飞书 Webhook 回调（Web 端点）。

        Args:
            payload: 飞书回调请求体

        Returns:
            应答字典
        """
        # 验证 challenge
        if payload.get("type") == "url_verification":
            challenge = payload.get("challenge", "")
            return {"challenge": challenge}

        # 处理消息事件
        event = payload.get("event", {})
        message_data = event.get("message", {})
        sender = event.get("sender", {})

        chat_id = message_data.get("chat_id", "")
        user_id = sender.get("sender_id", {}).get("open_id", "")
        msg_type = message_data.get("message_type", "")

        text = ""
        file_key = ""
        file_name = ""

        content = message_data.get("content", "{}")
        import json
        content_obj = json.loads(content) if isinstance(content, str) else content

        if msg_type == "text":
            text = content_obj.get("text", "")
        elif msg_type == "file":
            file_key = content_obj.get("file_key", "")
            file_name = content_obj.get("file_name", "unknown.pdf")
            text = "/convert"

        bot_message = BotMessage(
            platform="feishu",
            user_id=user_id,
            chat_id=chat_id,
            text=text,
            file_url=file_key,
            file_name=file_name,
        )
        await self.handle_message(bot_message)
        return {}

    # ---- 内部方法 ----

    async def _process_file(self, chat_id: str, user_id: str, message: BotMessage) -> None:
        await self.send_text(chat_id, "正在处理文件，请稍候...")

        try:
            if message.file_url:
                file_content = await self.client.download_file(message.file_url)
            else:
                await self.send_error(chat_id, "文件下载失败")
                return

            tmp_dir = Path(self.storage_root) / "bots" / "feishu" / user_id
            tmp_dir.mkdir(parents=True, exist_ok=True)
            local_path = tmp_dir / message.file_name

            with open(local_path, "wb") as f:
                f.write(file_content)

            job = self.job_service.create_job_from_file(
                source="feishu",
                input_file_path=str(local_path),
                original_filename=message.file_name,
                instruction=message.text.lstrip("/convert").strip(),
                options={},
            )
            self._user_jobs[user_id] = job.job_id
            await self.send_text(chat_id, f"任务已创建: {job.job_id[-8:]}\n使用 /status 查看进度。")

        except Exception as e:
            _log_bot_error("feishu", "file_processing", e)
            await self.send_error(chat_id, str(e))

    async def _send_job_status(self, chat_id: str, job_id: str) -> None:
        try:
            job = self.job_service.get_job(job_id)
            if not job:
                await self.send_text(chat_id, f"任务 {job_id[-8:]} 不存在。")
                return

            status = job.status
            status_msg = f"任务 {job_id[-8:]}: {status}"
            if job.progress_json:
                pct = job.progress_json.get("progress_percent", 0)
                status_msg += f"\n进度: {pct}%"
            if job.error_message:
                status_msg += f"\n错误: {_redact_secrets(job.error_message)}"

            await self.send_text(chat_id, status_msg)

        except Exception as e:
            await self.send_error(chat_id, str(e))


def _redact_secrets(text: str) -> str:
    """简单脱敏。"""
    import re
    text = re.sub(r'(token=|key=|app_secret=)\S+', r'\1***', text, flags=re.IGNORECASE)
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
