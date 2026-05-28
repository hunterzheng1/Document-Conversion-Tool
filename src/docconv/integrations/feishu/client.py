"""飞书 Open API httpx 客户端。

封装 tenant_access_token 自动获取与刷新、文件下载、消息发送。
token 不落日志，自动处理 token 过期刷新。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import httpx

from docconv.infra.bot_config import redact_secrets

logger = logging.getLogger(__name__)

FEISHU_HOST = "https://open.feishu.cn"

# 超时配置（秒）
SEND_TIMEOUT = 30
DOWNLOAD_TIMEOUT = 300

# 重试配置
MAX_RETRIES = 2
RETRY_DELAYS = [1, 3]

# Token 缓存 TTL（秒），飞书默认 7200s
TOKEN_TTL = 7000  # 略小于 7200 提前刷新


class FeishuClient:
    """飞书 Open API httpx 封装。

    职责：
    - tenant_access_token 自动获取与刷新
    - 文件下载
    - 消息发送（文本、文件）
    - 统一超时、重试
    - token/app_secret 自动脱敏日志
    """

    def __init__(self, app_id: str, app_secret: str, base_url: str = FEISHU_HOST):
        self.app_id = app_id
        self.app_secret = app_secret
        self.base_url = base_url
        self._send_client = httpx.AsyncClient(timeout=SEND_TIMEOUT)
        self._download_client = httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT)
        self._tenant_token = ""
        self._token_expires_at = 0.0

    async def close(self) -> None:
        await self._send_client.aclose()
        await self._download_client.aclose()

    async def get_tenant_access_token(self) -> str:
        """获取 tenant_access_token，自动缓存和刷新。

        Returns:
            有效的 tenant_access_token

        Raises:
            RuntimeError: 获取 token 失败
        """
        import time
        if self._tenant_token and time.time() < self._token_expires_at:
            return self._tenant_token

        await self._refresh_token()
        return self._tenant_token

    async def _refresh_token(self) -> None:
        """刷新 tenant_access_token。"""
        import time
        url = f"{self.base_url}/open-apis/auth/v3/tenant_access_token/internal"
        try:
            resp = await self._send_client.post(
                url,
                json={"app_id": self.app_id, "app_secret": self.app_secret},
            )
            resp.raise_for_status()
            data = resp.json()
            token = data.get("tenant_access_token", "")
            if not token:
                raise RuntimeError(f"飞书获取 token 失败: {data}")
            self._tenant_token = token
            expire = data.get("expire", 7200)
            self._token_expires_at = time.time() + expire - 60  # 提前 60s 刷新
            logger.debug("飞书 token 已刷新")
        except httpx.HTTPStatusError:
            logger.error("飞书 token 请求 HTTP 错误")
            raise
        except Exception as e:
            redacted = redact_secrets(str(e))
            logger.error("飞书 token 获取失败: %s", redacted)
            raise

    async def _request(
        self, method: str, api_path: str, **kwargs: Any,
    ) -> dict:
        """发送请求到飞书 API，自动附加 token。

        Args:
            method: HTTP 方法
            api_path: API 路径
            **kwargs: 请求参数

        Returns:
            API 响应中的 data 字段

        Raises:
            RuntimeError: API 返回错误码
        """
        token = await self.get_tenant_access_token()
        url = f"{self.base_url}{api_path}"
        headers = {"Authorization": f"Bearer {token}"}

        if method.upper() == "POST":
            resp = await self._send_client.post(
                url, headers=headers, json=kwargs.get("json", {}),
                params=kwargs.get("params"),
            )
        else:
            resp = await self._send_client.get(url, headers=headers, params=kwargs.get("params"))

        resp.raise_for_status()
        data = resp.json()

        # 检查飞书错误码
        code = data.get("code", -1)
        if code != 0:
            # token 可能过期，尝试刷新重试
            if code == 99991663 or code == 99991661:
                await self._refresh_token()
                token = await self.get_tenant_access_token()
                headers = {"Authorization": f"Bearer {token}"}
                if method.upper() == "POST":
                    resp = await self._send_client.post(
                        url, headers=headers, json=kwargs.get("json", {}),
                        params=kwargs.get("params"),
                    )
                else:
                    resp = await self._send_client.get(url, headers=headers, params=kwargs.get("params"))
                resp.raise_for_status()
                data = resp.json()
                code = data.get("code", -1)
                if code != 0:
                    raise RuntimeError(f"飞书 API 错误 (code={code}): {data.get('msg', '')}")
            else:
                raise RuntimeError(f"飞书 API 错误 (code={code}): {data.get('msg', '')}")

        return data.get("data", {})

    async def send_text(self, chat_id: str, text: str) -> dict:
        """发送文本消息。

        Args:
            chat_id: 目标会话 ID
            text: 消息文本

        Returns:
            API 响应数据
        """
        # 飞书消息 content 需要 JSON 字符串
        import json
        content = json.dumps({"text": text})
        return await self._request(
            "POST",
            "/open-apis/im/v1/messages",
            json={
                "receive_id_type": "chat_id",
                "msg_type": "text",
                "content": content,
            },
            params={"receive_id": chat_id},
        )

    async def send_file(self, chat_id: str, local_path: str, file_name: str = "") -> dict:
        """发送文件消息。

        Args:
            chat_id: 目标会话 ID
            local_path: 本地文件路径
            file_name: 文件名

        Returns:
            API 响应数据
        """
        import json

        # 1. 先上传文件获取 image_key/file_key
        file_key = await self._upload_file(local_path, file_name or Path(local_path).name)

        # 2. 发送文件消息
        content = json.dumps({"file_key": file_key})
        return await self._request(
            "POST",
            "/open-apis/im/v1/messages",
            json={
                "receive_id_type": "chat_id",
                "msg_type": "file",
                "content": content,
            },
            params={"receive_id": chat_id},
        )

    async def _upload_file(self, local_path: str, file_name: str) -> str:
        """上传文件到飞书获取 file_key。

        Args:
            local_path: 本地文件路径
            file_name: 文件名

        Returns:
            file_key
        """
        token = await self.get_tenant_access_token()
        url = f"{self.base_url}/open-apis/im/v1/files"
        headers = {"Authorization": f"Bearer {token}"}

        file_path = Path(local_path)
        with open(file_path, "rb") as f:
            files = {"file": (file_name, f, "application/octet-stream")}
            data = {"file_type": "stream"}
            resp = await self._send_client.post(url, headers=headers, files=files, data=data)

        resp.raise_for_status()
        result = resp.json()
        code = result.get("code", -1)
        if code != 0:
            raise RuntimeError(f"飞书文件上传失败 (code={code}): {result.get('msg', '')}")
        file_key = result.get("data", {}).get("file_key", "")
        if not file_key:
            raise RuntimeError("飞书文件上传未返回 file_key")
        return file_key

    async def download_file(self, file_key: str, dest_path: str) -> str:
        """从飞书下载文件到本地。

        Args:
            file_key: 飞书文件 key
            dest_path: 目标本地路径

        Returns:
            实际写入的本地文件路径
        """
        content = await self._download_with_retry(file_key)

        dest = Path(dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        logger.info("飞书文件已下载: %s (%d bytes)", dest.name, len(content))
        return str(dest)

    async def _download_file_content(self, file_key: str) -> bytes:
        """下载文件内容。

        Args:
            file_key: 飞书文件 key

        Returns:
            文件内容字节
        """
        token = await self.get_tenant_access_token()
        url = f"{self.base_url}/open-apis/im/v1/files/{file_key}"
        headers = {"Authorization": f"Bearer {token}"}
        resp = await self._download_client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.content

    async def _download_with_retry(self, file_key: str) -> bytes:
        """下载文件内容，支持重试。

        Args:
            file_key: 飞书文件 key

        Returns:
            文件内容字节

        Raises:
            RuntimeError: 所有重试均失败
        """
        last_error = None
        for attempt, delay in enumerate([0] + RETRY_DELAYS):
            if attempt > 0:
                logger.info("飞书下载重试 %d/%d, 等待 %ds", attempt, MAX_RETRIES, delay)
                await asyncio.sleep(delay)
            try:
                return await self._download_file_content(file_key)
            except Exception as e:
                last_error = e
        raise RuntimeError(f"飞书文件下载失败（重试 {MAX_RETRIES} 次后）: {redact_secrets(str(last_error))}")
