"""缓存管理器测试。"""

import sys
import os
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from docconv.infra.cache_manager import CacheManager


def test_cache_set_and_get():
    with tempfile.TemporaryDirectory() as tmp:
        cache = CacheManager({"cache_dir": tmp})
        cache.set("test_key", {"value": 123})
        assert cache.get("test_key") == {"value": 123}


def test_cache_get_missing():
    with tempfile.TemporaryDirectory() as tmp:
        cache = CacheManager({"cache_dir": tmp})
        assert cache.get("nonexistent") is None


def test_cache_invalidate():
    with tempfile.TemporaryDirectory() as tmp:
        cache = CacheManager({"cache_dir": tmp})
        cache.set("key1", "data")
        cache.invalidate("key1")
        assert cache.get("key1") is None


def test_cache_clear():
    with tempfile.TemporaryDirectory() as tmp:
        cache = CacheManager({"cache_dir": tmp})
        cache.set("k1", 1)
        cache.set("k2", 2)
        cache.clear()
        assert cache.get("k1") is None
        assert cache.get("k2") is None


def test_cache_disabled():
    with tempfile.TemporaryDirectory() as tmp:
        cache = CacheManager({"cache_dir": tmp, "enabled": False})
        cache.set("key", "data")
        assert cache.get("key") is None
