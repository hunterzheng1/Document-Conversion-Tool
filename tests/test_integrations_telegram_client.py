"""BI-04: Telegram HTTP 客户端测试。"""

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from docconv.integrations.telegram.client import (
    TelegramClient,
    _mask_token,
    SEND_TIMEOUT,
    DOWNLOAD_TIMEOUT,
    MAX_RETRIES,
)


@pytest.fixture()
def client():
    return TelegramClient(bot_token="test_bot_token_12345")


class TestMaskToken:
    def test_normal_token(self):
        result = _mask_token("1234567890:ABCdefghij1234567890")
        assert "1234" in result
        assert "****" not in result  # 用 ***
        assert "***" in result

    def test_short_token(self):
        assert _mask_token("abc") == "***"


class TestTelegramClient:
    def test_default_timeouts(self):
        assert SEND_TIMEOUT == 30
        assert DOWNLOAD_TIMEOUT == 300

    @pytest.mark.asyncio
    async def test_send_message_success(self, client):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True, "result": {"message_id": 1}}
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client, "_send_client") as mock_client:
            mock_client.post = AsyncMock(return_value=mock_resp)
            result = await client.send_message("chat123", "Hello")
            assert result == {"message_id": 1}

    @pytest.mark.asyncio
    async def test_send_message_api_error(self, client):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": False, "description": "chat not found"}
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client, "_send_client") as mock_client:
            mock_client.post = AsyncMock(return_value=mock_resp)
            with pytest.raises(RuntimeError, match="Telegram API error"):
                await client.send_message("chat123", "Hello")

    @pytest.mark.asyncio
    async def test_send_document(self, client):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True, "result": {"message_id": 2}}
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client, "_send_client") as mock_client:
            mock_client.post = AsyncMock(return_value=mock_resp)
            result = await client.send_document("chat123", "/path/to/file.pdf", caption="done")
            assert result == {"message_id": 2}

    @pytest.mark.asyncio
    async def test_get_file_info(self, client):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "ok": True,
            "result": {"file_path": "documents/file_123.pdf"},
        }
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client, "_send_client") as mock_client:
            mock_client.post = AsyncMock(return_value=mock_resp)
            result = await client.get_file_info("AgACAgEAA...")
            assert result["file_path"] == "documents/file_123.pdf"

    @pytest.mark.asyncio
    async def test_download_file_success(self, client):
        """测试完整的文件下载流程。"""
        # Mock getFile
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "ok": True,
            "result": {"file_path": "documents/test.pdf"},
        }
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client, "_send_client") as mock_send, \
             patch.object(client, "_download_client") as mock_dl:
            mock_send.post = AsyncMock(return_value=mock_resp)

            # Mock 文件下载
            mock_dl_resp = MagicMock()
            mock_dl_resp.content = b"PDF content here"
            mock_dl_resp.raise_for_status = MagicMock()
            mock_dl.get = AsyncMock(return_value=mock_dl_resp)

            with tempfile.TemporaryDirectory() as tmpdir:
                dest = Path(tmpdir) / "output" / "test.pdf"
                result = await client.download_file("file_id_123", str(dest))
                assert result == str(dest)
                assert Path(result).exists()
                assert Path(result).read_bytes() == b"PDF content here"

    @pytest.mark.asyncio
    async def test_download_file_no_file_path(self, client):
        """getFile 未返回 file_path 时抛异常。"""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True, "result": {}}
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client, "_send_client") as mock_send:
            mock_send.post = AsyncMock(return_value=mock_resp)
            with pytest.raises(RuntimeError, match="未返回 file_path"):
                await client.download_file("file_id_123", "/tmp/test.pdf")

    @pytest.mark.asyncio
    async def test_download_retry(self, client):
        """下载失败后重试。"""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "ok": True,
            "result": {"file_path": "documents/test.pdf"},
        }
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client, "_send_client") as mock_send, \
             patch.object(client, "_download_client") as mock_dl, \
             patch("docconv.integrations.telegram.client.asyncio.sleep", new_callable=AsyncMock):
            mock_send.post = AsyncMock(return_value=mock_resp)

            # 第一次失败，第二次成功
            mock_dl.get = AsyncMock(
                side_effect=[
                    httpx.HTTPStatusError("500", request=MagicMock(), response=MagicMock()),
                    MagicMock(content=b"retry content", raise_for_status=MagicMock()),
                ]
            )

            with tempfile.TemporaryDirectory() as tmpdir:
                dest = Path(tmpdir) / "test.pdf"
                result = await client.download_file("file_id_123", str(dest))
                assert result == str(dest)

    @pytest.mark.asyncio
    async def test_send_message_with_retry(self, client):
        """消息发送重试成功。"""
        with patch.object(client, "send_message", new_callable=AsyncMock) as mock_send:
            mock_send.side_effect = [
                RuntimeError("timeout"),
                {"message_id": 42},
            ]
            result = await client.send_message_with_retry("chat123", "Hello")
            assert result["message_id"] == 42
            assert mock_send.call_count == 2
