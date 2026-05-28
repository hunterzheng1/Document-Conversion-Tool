"""统一配置加载与 AppConfig 单元测试。"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))

import pytest
import yaml
from docconv.infra.config import (
    AppConfig,
    CacheConfig,
    JobsConfig,
    ModelsConfig,
    ServerConfig,
    StateConfig,
    StorageConfig,
    load_app_config,
)


def _write_yaml(data):
    """创建临时 YAML 文件，返回路径（调用者负责清理）。"""
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with open(fd, "w", encoding="utf-8") as f:
        yaml.dump(data, f)
    return path


# ---------------------------------------------------------------------------
# TASK-CLI-01: 配置加载
# ---------------------------------------------------------------------------

class TestLoadAppConfig:
    """测试统一配置加载函数。"""

    def test_file_not_exists_returns_empty(self):
        """YAML 文件不存在时返回空字典（不抛异常）。"""
        result = load_app_config("/nonexistent/path/config.yaml")
        assert result == {}

    def test_valid_yaml_loaded(self):
        """正常加载 YAML 配置。"""
        path = _write_yaml({"server": {"host": "0.0.0.0", "port": 9000}})
        try:
            result = load_app_config(path)
            assert result["server"]["host"] == "0.0.0.0"
            assert result["server"]["port"] == 9000
        finally:
            os.unlink(path)

    def test_yaml_parse_error_raises(self):
        """YAML 解析错误时抛出带明确消息的异常。"""
        fd, path = tempfile.mkstemp(suffix=".yaml")
        try:
            with open(fd, "w", encoding="utf-8") as f:
                f.write(": : :\n  - invalid: [unclosed")
            with pytest.raises(ValueError, match="YAML 配置解析失败"):
                load_app_config(path)
        finally:
            os.unlink(path)

    def test_env_var_priority(self):
        """环境变量 DOCCONV_CONFIG 优先级高于默认路径。"""
        path = _write_yaml({"server": {"host": "env-host"}})
        old = os.environ.get("DOCCONV_CONFIG")
        try:
            os.environ["DOCCONV_CONFIG"] = path
            result = load_app_config()  # 不传 path，应读环境变量
            assert result["server"]["host"] == "env-host"
        finally:
            if old is None:
                os.environ.pop("DOCCONV_CONFIG", None)
            else:
                os.environ["DOCCONV_CONFIG"] = old
            os.unlink(path)

    def test_legacy_key_cache_path_mapped(self):
        """旧键 cache.path 兼容映射为 cache.cache_dir。"""
        path = _write_yaml({"cache": {"path": "/old/cache"}})
        try:
            result = load_app_config(path)
            assert result["cache"]["cache_dir"] == "/old/cache"
        finally:
            os.unlink(path)

    def test_legacy_key_cache_ttl_days_mapped(self):
        """旧键 cache.ttl_days 兼容映射为 cache.ttl。"""
        path = _write_yaml({"cache": {"ttl_days": 30}})
        try:
            result = load_app_config(path)
            assert result["cache"]["ttl"] == 30
        finally:
            os.unlink(path)

    def test_legacy_key_resume_state_dir_mapped(self):
        """旧键 resume.state_dir 兼容映射为 state.state_dir。"""
        path = _write_yaml({"resume": {"state_dir": "/old/state"}})
        try:
            result = load_app_config(path)
            assert result["state"]["state_dir"] == "/old/state"
        finally:
            os.unlink(path)

    def test_empty_yaml_returns_empty(self):
        """空 YAML 文件返回空字典。"""
        fd, path = tempfile.mkstemp(suffix=".yaml")
        try:
            os.close(fd)
            result = load_app_config(path)
            assert result == {}
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# TASK-CLI-02: AppConfig dataclass
# ---------------------------------------------------------------------------

class TestAppConfig:
    """测试 AppConfig dataclass。"""

    def _make_storage_root(self):
        """创建临时存储根目录。"""
        return tempfile.mkdtemp()

    def test_default_values(self):
        """默认值与 design.md 一致。"""
        cfg = AppConfig(storage=StorageConfig(root=self._make_storage_root()))
        assert cfg.server.host == "127.0.0.1"
        assert cfg.server.port == 8000
        assert cfg.jobs.worker_id != ""  # hostname-pid

    def test_from_dict_applies_values(self):
        """from_dict 正确应用配置值。"""
        raw = {
            "server": {"host": "0.0.0.0", "port": 3000},
            "storage": {"root": self._make_storage_root()},
            "jobs": {"max_running": 5},
        }
        cfg = AppConfig.from_dict(raw)
        assert cfg.server.host == "0.0.0.0"
        assert cfg.server.port == 3000
        assert cfg.jobs.max_running == 5

    def test_validate_port_out_of_range_low(self):
        """port < 1 时抛 ValueError。"""
        cfg = AppConfig(
            server=ServerConfig(port=0),
            storage=StorageConfig(root=self._make_storage_root()),
        )
        with pytest.raises(ValueError, match="server.port 越界"):
            cfg.validate()

    def test_validate_port_out_of_range_high(self):
        """port > 65535 时抛 ValueError。"""
        cfg = AppConfig(
            server=ServerConfig(port=70000),
            storage=StorageConfig(root=self._make_storage_root()),
        )
        with pytest.raises(ValueError, match="server.port 越界"):
            cfg.validate()

    def test_validate_storage_root_not_exists(self):
        """storage.root 不存在时抛 ValueError。"""
        cfg = AppConfig(
            server=ServerConfig(port=8000),
            storage=StorageConfig(root="/nonexistent/path/xyz"),
        )
        with pytest.raises(ValueError, match="storage.root 路径不存在"):
            cfg.validate()

    def test_validate_pass(self):
        """有效配置通过校验。"""
        root = self._make_storage_root()
        cfg = AppConfig(
            server=ServerConfig(port=8000),
            storage=StorageConfig(root=root),
        )
        cfg.validate()  # 不应抛异常

    def test_to_dict(self):
        """to_dict 序列化不包含 api_key。"""
        root = self._make_storage_root()
        cfg = AppConfig(
            server=ServerConfig(host="0.0.0.0", port=9000),
            storage=StorageConfig(root=root),
            models=ModelsConfig(api_key="sk-secret"),
        )
        d = cfg.to_dict()
        assert d["server"]["host"] == "0.0.0.0"
        assert d["server"]["port"] == 9000
        assert "api_key" not in d.get("models", {})

    def test_server_config_ignored_in_convert(self):
        """无关配置段（如 server）在 convert 命令中静默忽略。

        AppConfig 仍然解析这些配置，但 convert 命令不使用它们。
        这里验证 AppConfig 不因为这些配置抛异常。
        """
        root = self._make_storage_root()
        raw = {
            "server": {"host": "0.0.0.0", "port": 5000},
            "storage": {"root": root},
        }
        cfg = AppConfig.from_dict(raw)
        cfg.validate()  # 不应抛异常
        # convert 可以安全忽略 server 段
