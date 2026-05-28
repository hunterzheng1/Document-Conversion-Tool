"""Server 配置单元测试 (TASK-WA-18)。"""

from __future__ import annotations

import os
from unittest.mock import patch

from docconv.web.api.app import DEFAULT_SERVER_CONFIG, _merge_config


class TestDefaultServerConfig:
    """默认 server 配置测试。"""

    def test_host_default(self):
        assert DEFAULT_SERVER_CONFIG["host"] == "0.0.0.0"

    def test_port_default(self):
        assert DEFAULT_SERVER_CONFIG["port"] == 8000

    def test_api_prefix_default(self):
        assert DEFAULT_SERVER_CONFIG["api_prefix"] == "/api/v1"

    def test_upload_max_file_size_mb_default(self):
        assert DEFAULT_SERVER_CONFIG["upload"]["max_file_size_mb"] == 100

    def test_upload_allowed_extensions_default(self):
        assert DEFAULT_SERVER_CONFIG["upload"]["allowed_extensions"] == [".pdf"]

    def test_auth_disabled_by_default(self):
        assert DEFAULT_SERVER_CONFIG["auth"]["enabled"] is False

    def test_docs_enabled_by_default(self):
        assert DEFAULT_SERVER_CONFIG["docs"]["enabled"] is True

    def test_public_base_url_null_by_default(self):
        assert DEFAULT_SERVER_CONFIG.get("public_base_url") is None


class TestMergeConfig:
    """配置合并测试。"""

    def test_no_overrides_returns_defaults(self):
        result = _merge_config()
        assert result["host"] == "0.0.0.0"
        assert result["port"] == 8000

    def test_override_top_level(self):
        result = _merge_config({"host": "127.0.0.1"})
        assert result["host"] == "127.0.0.1"
        assert result["port"] == 8000  # unchanged

    def test_override_nested_dict(self):
        result = _merge_config({"upload": {"max_file_size_mb": 200}})
        assert result["upload"]["max_file_size_mb"] == 200
        assert result["upload"]["allowed_extensions"] == [".pdf"]  # unchanged

    def test_replace_non_dict_value(self):
        """非 dict 类型配置项完全替换。"""
        result = _merge_config({"auth": {"enabled": True, "token": "secret"}})
        assert result["auth"]["enabled"] is True
        assert result["auth"]["token"] == "secret"


class TestEnvOverride:
    """环境变量覆盖测试。"""

    def test_doconv_server_port_override(self):
        with patch.dict(os.environ, {"DOCONV_SERVER_PORT": "9000"}, clear=False):
            result = _merge_config()
            assert result["port"] == 9000

    def test_doconv_server_host_override(self):
        with patch.dict(os.environ, {"DOCONV_SERVER_HOST": "127.0.0.1"}, clear=False):
            result = _merge_config()
            assert result["host"] == "127.0.0.1"

    def test_env_port_overrides_config_param(self):
        """环境变量优先级高于 config 参数。"""
        with patch.dict(os.environ, {"DOCONV_SERVER_PORT": "7000"}, clear=False):
            result = _merge_config({"port": 8888})
            assert result["port"] == 7000  # env wins
