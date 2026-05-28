"""BI-07: 飞书 HTTP 客户端测试。"""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from docconv.integrations.feishu.client import (
    FeishuClient,
    SEND_TIMEOUT,
    DOWNLOAD_TIMEOUT,
    MAX_RETRIES,
)


@pytest.fixture()
def client():
    return FeishuClient(app_id="cli_test_app", app_secret="test_secret_1234567890")


class TestTimeouts:
    def test_default_timeouts(self):
        assert SEND_TIMEOUT == 30
        assert DOWNLOAD_TIMEOUT == 300


class TestTokenManagement:
    @pytest.mark.asyncio
    async def test_get_tenant_access_token(self, client):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "code": 0,
            "tenant_access_token": "t-test-token-1234567890",
            "expire": 7200,
        }
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client, "_send_client") as mock_send:
            mock_send.post = AsyncMock(return_value=mock_resp)
            token = await client.get_tenant_access_token()
            assert token == "t-test-token-1234567890"

    @pytest.mark.asyncio
    async def test_token_cached(self, client):
        """token 未过期时应直接返回缓存值。"""
        # 先获取一次 token
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "code": 0,
            "tenant_access_token": "cached-token",
            "expire": 7200,
        }
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client, "_send_client") as mock_send:
            mock_send.post = AsyncMock(return_value=mock_resp)
            token1 = await client.get_tenant_access_token()
            assert token1 == "cached-token"

            # 第二次不应再调用 post
            mock_send.post.reset_mock()
            token2 = await client.get_tenant_access_token()
            assert token2 == "cached-token"
            mock_send.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_token_refresh_on_expiry(self, client):
        """token 过期后应自动刷新。"""
        import time
        client._tenant_token = "expired-token"
        client._token_expires_at = time.time() - 100  # 已过期

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "code": 0,
            "tenant_access_token": "new-token",
            "expire": 7200,
        }
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client, "_send_client") as mock_send:
            mock_send.post = AsyncMock(return_value=mock_resp)
            token = await client.get_tenant_access_token()
            assert token == "new-token"


class TestSendMessage:
    @pytest.mark.asyncio
    async def test_send_text(self, client):
        client._tenant_token = "test-token"
        client._token_expires_at = float("inf")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"code": 0, "data": {"message_id": "msg_001"}}
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client, "_send_client") as mock_send:
            mock_send.post = AsyncMock(return_value=mock_resp)
            result = await client.send_text("oc_test_chat", "Hello from bot")
            assert result["message_id"] == "msg_001"


class TestDownloadFile:
    @pytest.mark.asyncio
    async def test_download_file_success(self, client):
        client._tenant_token = "test-token"
        client._token_expires_at = float("inf")

        mock_resp = MagicMock()
        mock_resp.content = b"PDF binary content"
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client, "_download_client") as mock_dl:
            mock_dl.get = AsyncMock(return_value=mock_resp)

            with tempfile.TemporaryDirectory() as tmpdir:
                dest = Path(tmpdir) / "output" / "test.pdf"
                result = await client.download_file("file_key_123", str(dest))
                assert result == str(dest)
                assert Path(result).exists()
                assert Path(result).read_bytes() == b"PDF binary content"

    @pytest.mark.asyncio
    async def test_download_retry(self, client):
        client._tenant_token = "test-token"
        client._token_expires_at = float("inf")

        with patch.object(client, "_download_client") as mock_dl, \
             patch("docconv.integrations.feishu.client.asyncio.sleep", new_callable=AsyncMock):
            mock_dl.get = AsyncMock(
                side_effect=[
                    httpx.HTTPStatusError("500", request=MagicMock(), response=MagicMock()),
                    MagicMock(content=b"retry content", raise_for_status=MagicMock()),
                ]
            )

            with tempfile.TemporaryDirectory() as tmpdir:
                dest = Path(tmpdir) / "test.pdf"
                result = await client.download_file("file_key_123", str(dest))
                assert result == str(dest)


class TestSendFile:
    @pytest.mark.asyncio
    async def test_send_file(self, client):
        client._tenant_token = "test-token"
        client._token_expires_at = float("inf")

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "report.pdf"
            test_file.write_bytes(b"PDF content")

            # Mock 上传响应
            upload_resp = MagicMock()
            upload_resp.json.return_value = {"code": 0, "data": {"file_key": "key_123"}}
            upload_resp.raise_for_status = MagicMock()

            # Mock 发送响应
            send_resp = MagicMock()
            send_resp.json.return_value = {"code": 0, "data": {"message_id": "msg_002"}}
            send_resp.raise_for_status = MagicMock()

            with patch.object(client, "_send_client") as mock_send:
                mock_send.post = AsyncMock(side_effect=[upload_resp, send_resp])
                result = await client.send_file("oc_test_chat", str(test_file), "report.pdf")
                assert result["message_id"] == "msg_002"
