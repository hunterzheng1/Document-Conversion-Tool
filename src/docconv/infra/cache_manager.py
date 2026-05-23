"""缓存管理器：基于文件系统 + SQLite 索引的缓存。"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


@dataclass
class CacheEntry:
    """缓存条目。"""
    cache_key: str
    content_type: str = ""
    content: str = ""
    model_id: str = ""
    prompt_version: str = ""
    quality: dict = None
    created_at: float = 0.0

    def __post_init__(self):
        if self.quality is None:
            self.quality = {}
        if self.created_at == 0.0:
            self.created_at = time.time()


class CacheManager:
    """基于文件系统 + SQLite 索引的缓存管理器。"""

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self._cache_dir = Path(cfg.get("cache_dir", ".cache/docconv"))
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._objects_dir = self._cache_dir / "objects"
        self._objects_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self._cache_dir / "index.db"
        self._ttl = cfg.get("ttl", 86400 * 14)  # 默认 14 天
        self._max_size_gb = cfg.get("max_size_gb", 5)
        self._sensitive_mode = cfg.get("sensitive_mode", False)
        self._enabled = cfg.get("enabled", True)
        self._prompt_version = cfg.get("prompt_version", "v1")
        self._init_db()

    def _init_db(self):
        """初始化 SQLite 索引。"""
        conn = sqlite3.connect(str(self._db_path))
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cache_index (
                cache_key TEXT PRIMARY KEY,
                content_type TEXT,
                model_id TEXT,
                prompt_version TEXT,
                file_path TEXT,
                file_size INTEGER,
                created_at REAL
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON cache_index(created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_content_type ON cache_index(content_type)")
        conn.commit()
        conn.close()

    def generate_cache_key(
        self,
        image_path: str,
        prompt_version: str,
        model_id: str,
        content_type: str = "",
        converter_version: str = "v1",
    ) -> str:
        """生成缓存 key。"""
        image_hash = self._compute_image_hash(image_path)
        raw = f"{image_hash}:{prompt_version}:{model_id}:{content_type}:{converter_version}"
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def _compute_image_hash(image_path: str) -> str:
        h = hashlib.sha256()
        with open(image_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    def get_cache(self, key: str) -> CacheEntry | None:
        """查询缓存。"""
        if not self._enabled:
            return None

        conn = sqlite3.connect(str(self._db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT file_path FROM cache_index WHERE cache_key = ?", (key,))
        row = cursor.fetchone()
        conn.close()

        if row is None:
            return None

        file_path = Path(row[0])
        if not file_path.exists():
            self._remove_from_db(key)
            return None

        # 检查 TTL
        try:
            with open(file_path) as f:
                data = json.load(f)
            if time.time() - data.get("timestamp", 0) > self._ttl:
                self._cleanup_entry(key, file_path)
                return None
            return CacheEntry(**data.get("entry", {}))
        except (json.JSONDecodeError, OSError):
            self._cleanup_entry(key, file_path)
            return None

    def set_cache(self, key: str, entry: CacheEntry) -> None:
        """写入缓存。"""
        if not self._enabled or self._sensitive_mode:
            return

        file_path = self._objects_dir / f"{key}.json"
        tmp_file = file_path.with_suffix(".tmp")

        data = {
            "timestamp": time.time(),
            "entry": asdict(entry),
        }
        with open(tmp_file, "w") as f:
            json.dump(data, f)

        os.replace(tmp_file, file_path)

        # 写入 SQLite 索引
        conn = sqlite3.connect(str(self._db_path))
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO cache_index
            (cache_key, content_type, model_id, prompt_version, file_path, file_size, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            key,
            entry.content_type,
            entry.model_id,
            entry.prompt_version,
            str(file_path),
            file_path.stat().st_size,
            entry.created_at,
        ))
        conn.commit()
        conn.close()

        # 检查大小限制
        self._enforce_size_limit()

    def invalidate(self, key: str) -> None:
        """使缓存失效。"""
        self._cleanup_key(key)

    def clear(self) -> None:
        """清空所有缓存。"""
        conn = sqlite3.connect(str(self._db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT file_path FROM cache_index")
        for row in cursor.fetchall():
            try:
                Path(row[0]).unlink(missing_ok=True)
            except OSError:
                pass
        cursor.execute("DELETE FROM cache_index")
        conn.commit()
        conn.close()

    def get_stats(self) -> dict:
        """返回缓存统计信息。"""
        conn = sqlite3.connect(str(self._db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*), COALESCE(SUM(file_size), 0) FROM cache_index")
        count, total_size = cursor.fetchone()

        # 计算命中率
        cursor.execute("SELECT COUNT(*) FROM cache_index WHERE created_at > ?", (time.time() - 86400,))
        recent = cursor.fetchone()[0]
        conn.close()

        return {
            "entries": count,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "recent_entries_24h": recent,
        }

    def get_size(self) -> int:
        """获取缓存大小（字节）。"""
        stats = self.get_stats()
        return stats["total_size_bytes"]

    # --- 内部方法 ---

    def _remove_from_db(self, key: str):
        conn = sqlite3.connect(str(self._db_path))
        cursor = conn.cursor()
        cursor.execute("DELETE FROM cache_index WHERE cache_key = ?", (key,))
        conn.commit()
        conn.close()

    def _cleanup_entry(self, key: str, file_path: Path):
        try:
            file_path.unlink(missing_ok=True)
        except OSError:
            pass
        self._remove_from_db(key)

    def _cleanup_key(self, key: str):
        conn = sqlite3.connect(str(self._db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT file_path FROM cache_index WHERE cache_key = ?", (key,))
        row = cursor.fetchone()
        if row:
            try:
                Path(row[0]).unlink(missing_ok=True)
            except OSError:
                pass
        cursor.execute("DELETE FROM cache_index WHERE cache_key = ?", (key,))
        conn.commit()
        conn.close()

    def _enforce_size_limit(self):
        """按 LRU 清理超过大小限制的缓存。"""
        max_bytes = self._max_size_gb * 1024 * 1024 * 1024
        conn = sqlite3.connect(str(self._db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT SUM(file_size) FROM cache_index")
        total = cursor.fetchone()[0] or 0

        while total > max_bytes:
            cursor.execute("SELECT cache_key, file_size FROM cache_index ORDER BY created_at ASC LIMIT 1")
            row = cursor.fetchone()
            if row is None:
                break
            key, size = row
            cursor.execute("SELECT file_path FROM cache_index WHERE cache_key = ?", (key,))
            fp_row = cursor.fetchone()
            if fp_row:
                try:
                    Path(fp_row[0]).unlink(missing_ok=True)
                except OSError:
                    pass
            cursor.execute("DELETE FROM cache_index WHERE cache_key = ?", (key,))
            total -= size

        conn.commit()
        conn.close()
