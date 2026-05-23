"""缓存管理器测试。"""

import sys
import os
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from docconv.infra.cache_manager import CacheManager, CacheEntry


def test_cache_set_and_get():
    with tempfile.TemporaryDirectory() as tmp:
        cache = CacheManager({"cache_dir": tmp})
        entry = CacheEntry(cache_key="test_key", content="value", content_type="text")
        cache.set_cache("test_key", entry)
        result = cache.get_cache("test_key")
        assert result is not None
        assert result.content == "value"


def test_cache_get_missing():
    with tempfile.TemporaryDirectory() as tmp:
        cache = CacheManager({"cache_dir": tmp})
        assert cache.get_cache("nonexistent") is None


def test_cache_invalidate():
    with tempfile.TemporaryDirectory() as tmp:
        cache = CacheManager({"cache_dir": tmp})
        entry = CacheEntry(cache_key="key1", content="data")
        cache.set_cache("key1", entry)
        cache.invalidate("key1")
        assert cache.get_cache("key1") is None


def test_cache_clear():
    with tempfile.TemporaryDirectory() as tmp:
        cache = CacheManager({"cache_dir": tmp})
        cache.set_cache("k1", CacheEntry(cache_key="k1", content="1"))
        cache.set_cache("k2", CacheEntry(cache_key="k2", content="2"))
        cache.clear()
        assert cache.get_cache("k1") is None
        assert cache.get_cache("k2") is None


def test_cache_disabled():
    with tempfile.TemporaryDirectory() as tmp:
        cache = CacheManager({"cache_dir": tmp, "enabled": False})
        cache.set_cache("key", CacheEntry(cache_key="key", content="data"))
        assert cache.get_cache("key") is None


def test_generate_cache_key():
    import tempfile
    img_path = os.path.join(tempfile.gettempdir(), "test_cache_img.png")
    with open(img_path, "wb") as f:
        f.write(b"test image data" * 100)
    try:
        cache = CacheManager()
        key1 = cache.generate_cache_key(img_path, "v1", "model-a", "table", "v1")
        key2 = cache.generate_cache_key(img_path, "v2", "model-a", "table", "v1")
        assert key1 != key2, "不同 prompt_version 应产生不同的缓存 key"
    finally:
        try:
            os.remove(img_path)
        except OSError:
            pass


def test_cache_stats():
    with tempfile.TemporaryDirectory() as tmp:
        cache = CacheManager({"cache_dir": tmp})
        cache.set_cache("k1", CacheEntry(cache_key="k1", content="1"))
        stats = cache.get_stats()
        assert stats["entries"] >= 1
        assert "total_size_bytes" in stats
