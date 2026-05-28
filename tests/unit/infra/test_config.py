"""配置归一化测试（TASK-CM-01）。"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))

import pytest
from docconv.infra.config import normalize_cache_config, CacheConfigError, MIN_TTL_SECONDS, MAX_TTL_SECONDS


class TestNormalizeCacheConfigNormal:
    """正常输入测试。"""

    def test_default_config(self):
        """无输入时使用默认值。"""
        result = normalize_cache_config()
        assert result["cache_dir"] == ".cache/docconv"
        assert result["ttl"] == 14 * 86400
        assert result["max_size_gb"] == 5.0
        assert result["enabled"] is True
        assert result["prompt_version"] == "v1"
        assert result["sensitive_mode"] is False

    def test_empty_dict(self):
        """空字典使用默认值。"""
        result = normalize_cache_config({})
        assert result["cache_dir"] == ".cache/docconv"

    def test_path_maps_to_cache_dir(self):
        """path 自动映射为 cache_dir。"""
        result = normalize_cache_config({"path": "/tmp/cache"})
        assert result["cache_dir"] == "/tmp/cache"

    def test_cache_dir_preferred(self):
        """cache_dir 优先于 path。"""
        result = normalize_cache_config({"cache_dir": "/a", "path": "/b"})
        assert result["cache_dir"] == "/a"

    def test_ttl_days_converted(self):
        """ttl_days 自动转为秒。"""
        result = normalize_cache_config({"ttl_days": 30})
        assert result["ttl"] == 30 * 86400

    def test_ttl_preferred_over_ttl_days(self):
        """ttl 和 ttl_days 同时存在时优先使用 ttl。"""
        result = normalize_cache_config({"ttl": 100000, "ttl_days": 30})
        assert result["ttl"] == 100000

    def test_full_custom_config(self):
        """完整自定义配置。"""
        cfg = {
            "cache_dir": "/custom/cache",
            "ttl": 200000,
            "max_size_gb": 10,
            "enabled": False,
            "prompt_version": "v2",
            "sensitive_mode": True,
        }
        result = normalize_cache_config(cfg)
        assert result == {
            "cache_dir": "/custom/cache",
            "ttl": 200000,
            "max_size_gb": 10.0,
            "enabled": False,
            "prompt_version": "v2",
            "sensitive_mode": True,
        }


class TestNormalizeCacheConfigBoundary:
    """边界值测试。"""

    def test_min_ttl(self):
        """最小 TTL（1天）。"""
        result = normalize_cache_config({"ttl": MIN_TTL_SECONDS})
        assert result["ttl"] == MIN_TTL_SECONDS

    def test_max_ttl(self):
        """最大 TTL（365天）。"""
        result = normalize_cache_config({"ttl": MAX_TTL_SECONDS})
        assert result["ttl"] == MAX_TTL_SECONDS

    def test_max_size_gb_float(self):
        """max_size_gb 支持浮点数。"""
        result = normalize_cache_config({"max_size_gb": 2.5})
        assert result["max_size_gb"] == 2.5


class TestNormalizeCacheConfigInvalid:
    """非法配置测试。"""

    def test_ttl_too_small(self):
        """ttl 过小抛出 CA1001。"""
        with pytest.raises(CacheConfigError) as exc:
            normalize_cache_config({"ttl": 1000})
        assert exc.value.error_code == "CA1001"
        assert "超出范围" in str(exc.value)

    def test_ttl_too_large(self):
        """ttl 过大抛出 CA1001。"""
        with pytest.raises(CacheConfigError) as exc:
            normalize_cache_config({"ttl": MAX_TTL_SECONDS + 86400})
        assert exc.value.error_code == "CA1001"

    def test_max_size_gb_zero(self):
        """max_size_gb 为 0 抛出 CA1001。"""
        with pytest.raises(CacheConfigError) as exc:
            normalize_cache_config({"max_size_gb": 0})
        assert exc.value.error_code == "CA1001"

    def test_max_size_gb_negative(self):
        """max_size_gb 为负数抛出 CA1001。"""
        with pytest.raises(CacheConfigError) as exc:
            normalize_cache_config({"max_size_gb": -1})
        assert exc.value.error_code == "CA1001"

    def test_empty_cache_dir(self):
        """cache_dir 为空字符串抛出 CA1001。"""
        with pytest.raises(CacheConfigError) as exc:
            normalize_cache_config({"cache_dir": "  "})
        assert exc.value.error_code == "CA1001"

    def test_path_traversal_denied(self):
        """路径穿越被拒绝。"""
        with pytest.raises(CacheConfigError) as exc:
            normalize_cache_config({"cache_dir": "../../etc/passwd"})
        assert exc.value.error_code == "CA1001"
        assert "路径穿越" in str(exc.value)
