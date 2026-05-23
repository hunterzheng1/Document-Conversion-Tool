"""缓存管理器：基于文件系统的缓存。"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any


class CacheManager:
    """基于文件系统的缓存管理器。"""

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self._cache_dir = Path(cfg.get("cache_dir", ".cache/docconv"))
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._ttl = cfg.get("ttl", 86400)  # 默认 24 小时
        self._enabled = cfg.get("enabled", True)

    def _make_key(self, *args: Any) -> str:
        """生成缓存键。"""
        raw = json.dumps(args, default=str, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, key: str) -> Any | None:
        """获取缓存值。"""
        if not self._enabled:
            return None

        cache_file = self._cache_dir / f"{key}.json"
        if not cache_file.exists():
            return None

        try:
            with open(cache_file) as f:
                data = json.load(f)

            if time.time() - data.get("timestamp", 0) > self._ttl:
                cache_file.unlink()
                return None

            return data.get("value")
        except (json.JSONDecodeError, OSError):
            return None

    def set(self, key: str, value: Any) -> None:
        """设置缓存值（原子写入）。"""
        if not self._enabled:
            return

        cache_file = self._cache_dir / f"{key}.json"
        tmp_file = cache_file.with_suffix(".tmp")

        data = {"timestamp": time.time(), "value": value}
        with open(tmp_file, "w") as f:
            json.dump(data, f)

        os.replace(tmp_file, cache_file)

    def invalidate(self, key: str) -> None:
        """使缓存失效。"""
        cache_file = self._cache_dir / f"{key}.json"
        if cache_file.exists():
            cache_file.unlink()

    def clear(self) -> None:
        """清空所有缓存。"""
        for f in self._cache_dir.glob("*.json"):
            f.unlink()

    def get_size(self) -> int:
        """获取缓存大小（字节）。"""
        return sum(f.stat().st_size for f in self._cache_dir.glob("*.json"))
