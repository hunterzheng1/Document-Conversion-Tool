"""缓存管理器：基于文件系统 + SQLite 索引的缓存。"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 错误码
# ---------------------------------------------------------------------------
CACHE_CONFIG_ERROR = "CA1001"
CACHE_HIT_UNAVAILABLE = "CA2001"
CACHE_WRITE_FAILED = "CA5001"
CACHE_CLEANUP_FAILED = "CA5002"


class CacheConfigError(ValueError):
    """缓存配置异常。"""

    def __init__(self, message: str, error_code: str = CACHE_CONFIG_ERROR):
        self.error_code = error_code
        super().__init__(f"[{error_code}] {message}")


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# CacheManager
# ---------------------------------------------------------------------------
class CacheManager:
    """基于文件系统 + SQLite 索引的缓存管理器。"""

    def __init__(self, config: dict | None = None):
        cfg = config or {}

        # 配置归一化：兼容 path/cache_dir, ttl_days/ttl
        cache_dir = cfg.get("cache_dir") or cfg.get("path", ".cache/docconv")
        ttl = cfg.get("ttl")
        if ttl is None:
            ttl_days = cfg.get("ttl_days", 14)
            ttl = ttl_days * 86400

        # 校验配置
        if not str(cache_dir).strip():
            raise CacheConfigError("cache_dir 不能为空")
        if ".." in str(cache_dir):
            raise CacheConfigError(f"cache_dir 包含非法路径穿越: {cache_dir}")

        min_ttl = 86400
        max_ttl = 31536000
        if ttl < min_ttl or ttl > max_ttl:
            raise CacheConfigError(
                f"ttl 超出范围: {ttl} 秒，必须在 {min_ttl} ~ {max_ttl} 秒之间"
            )

        max_size_gb = cfg.get("max_size_gb", 5)
        if not isinstance(max_size_gb, (int, float)) or max_size_gb <= 0:
            raise CacheConfigError(f"max_size_gb 必须大于 0，当前值: {max_size_gb}")

        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._objects_dir = self._cache_dir / "objects"
        self._objects_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self._cache_dir / "index.db"
        self._ttl = ttl
        self._max_size_gb = float(max_size_gb)
        self._sensitive_mode = cfg.get("sensitive_mode", False)
        self._enabled = cfg.get("enabled", True)
        self._prompt_version = cfg.get("prompt_version", "v1")

        # TASK-CM-02: 多租户隔离 + 内容哈希
        self._tenant_id = cfg.get("tenant_id", "")
        self._content_hash_enabled = cfg.get("content_hash_enabled", False)

        # TASK-CM-11: 命中率计数器
        self._hits = 0
        self._misses = 0

        self._init_db()

    # ---- 兼容别名 ----

    def get(self, key: str) -> CacheEntry | None:
        """get_cache 的别名（TASK-CM-03）。"""
        return self.get_cache(key)

    def set(self, key: str, entry: CacheEntry) -> None:
        """set_cache 的别名（TASK-CM-03）。"""
        self.set_cache(key, entry)

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

        # TASK-CM-07: LRU 支持 — 新增 last_accessed_at 字段（幂等）
        try:
            cursor.execute("ALTER TABLE cache_index ADD COLUMN last_accessed_at REAL")
        except sqlite3.OperationalError:
            pass  # 字段已存在

        # 初始化 last_accessed_at 为 created_at（迁移旧数据）
        cursor.execute("""
            UPDATE cache_index
            SET last_accessed_at = created_at
            WHERE last_accessed_at IS NULL
        """)

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_last_accessed ON cache_index(last_accessed_at)")
        conn.commit()
        conn.close()

    # ---- 缓存 key 生成 ----

    def generate_cache_key(
        self,
        image_path: str,
        prompt_version: str,
        model_id: str,
        content_type: str = "",
        converter_version: str = "v1",
    ) -> str:
        """生成缓存 key（TASK-CM-05：加入 tenant_id）。"""
        image_hash = self._compute_image_hash(image_path)
        raw = f"{self._tenant_id}:{image_hash}:{prompt_version}:{model_id}:{content_type}:{converter_version}"
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def _compute_image_hash(image_path: str) -> str:
        h = hashlib.sha256()
        with open(image_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    # ---- TASK-CM-06: PDF 内容哈希 ----

    def _compute_pdf_content_hash(self, pdf_path: str) -> str:
        """计算 PDF 文件内容哈希，用于相似文档共享缓存。

        对相同 PDF 内容返回相同哈希（与路径无关）。
        """
        h = hashlib.sha256()
        with open(pdf_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    def generate_cache_key_from_pdf(
        self,
        pdf_path: str,
        page_num: int,
        prompt_version: str,
        model_id: str,
        content_type: str = "",
        converter_version: str = "v1",
    ) -> str:
        """从 PDF 路径生成缓存 key，使用内容哈希。

        当 content_hash_enabled=True 时，使用 PDF 内容哈希替代图像哈希。
        """
        if self._content_hash_enabled:
            content_hash = self._compute_pdf_content_hash(pdf_path)
            raw = f"{self._tenant_id}:{content_hash}:page_{page_num}:{prompt_version}:{model_id}:{content_type}:{converter_version}"
        else:
            raw = f"{self._tenant_id}:{pdf_path}:page_{page_num}:{prompt_version}:{model_id}:{content_type}:{converter_version}"
        return hashlib.sha256(raw.encode()).hexdigest()

    # ---- 敏感模式日志 ----

    def _log_sensitive_operation(self, msg: str):
        """对敏感模式下的缓存操作进行脱敏日志记录（TASK-CM-09）。

        日志中不包含 cache key 或内容信息。
        """
        logger.info(f"[cache:sensitive] {msg}")

    # ---- 缓存查询 ----

    def get_cache(self, key: str) -> CacheEntry | None:
        """查询缓存。

        TASK-CM-09: 敏感模式直接返回 None。
        TASK-CM-07: 命中时更新 last_accessed_at。
        TASK-CM-11: 更新命中/未命中计数。
        """
        if not self._enabled:
            self._misses += 1
            return None

        if self._sensitive_mode:
            self._log_sensitive_operation("get_cache bypassed (sensitive mode)")
            self._misses += 1
            return None

        conn = sqlite3.connect(str(self._db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT file_path FROM cache_index WHERE cache_key = ?", (key,))
        row = cursor.fetchone()
        conn.close()

        if row is None:
            self._misses += 1
            return None

        file_path = Path(row[0])
        if not file_path.exists():
            self._cleanup_entry(key, file_path)
            self._misses += 1
            return None

        # 检查 TTL
        try:
            with open(file_path) as f:
                data = json.load(f)
            if time.time() - data.get("timestamp", 0) > self._ttl:
                self._cleanup_entry(key, file_path)
                self._misses += 1
                return None
            entry = CacheEntry(**data.get("entry", {}))

            # TASK-CM-07: 更新 last_accessed_at
            self._update_last_accessed(key)

            self._hits += 1
            return entry
        except (json.JSONDecodeError, OSError):
            self._cleanup_entry(key, file_path)
            self._misses += 1
            return None

    # ---- 缓存写入 ----

    def set_cache(self, key: str, entry: CacheEntry) -> None:
        """写入缓存。

        TASK-CM-09: 敏感模式直接返回。
        """
        if not self._enabled:
            return

        if self._sensitive_mode:
            self._log_sensitive_operation("set_cache bypassed (sensitive mode)")
            return

        file_path = self._objects_dir / f"{key}.json"
        tmp_file = file_path.with_suffix(".tmp")

        data = {
            "timestamp": time.time(),
            "entry": asdict(entry),
        }
        try:
            with open(tmp_file, "w") as f:
                json.dump(data, f)
            os.replace(tmp_file, file_path)
        except OSError as exc:
            logger.error(f"[cache] set_cache 写入失败: {exc}")
            return

        # 写入 SQLite 索引
        conn = sqlite3.connect(str(self._db_path))
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO cache_index
            (cache_key, content_type, model_id, prompt_version, file_path, file_size, created_at, last_accessed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            key,
            entry.content_type,
            entry.model_id,
            entry.prompt_version,
            str(file_path),
            file_path.stat().st_size,
            entry.created_at,
            time.time(),  # last_accessed_at
        ))
        conn.commit()
        conn.close()

        # 检查大小限制
        self._enforce_size_limit()

    # ---- 缓存失效 ----

    def invalidate(self, key: str) -> None:
        """使缓存失效。"""
        self._cleanup_key(key)

    def clear(self) -> int:
        """清空所有缓存。

        Returns:
            清理的条目数量（TASK-CM-10）。
        """
        conn = sqlite3.connect(str(self._db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM cache_index")
        count = cursor.fetchone()[0]

        cursor.execute("SELECT file_path FROM cache_index")
        for row in cursor.fetchall():
            try:
                Path(row[0]).unlink(missing_ok=True)
            except OSError:
                pass
        cursor.execute("DELETE FROM cache_index")
        conn.commit()
        conn.close()

        # 重置计数器
        self._hits = 0
        self._misses = 0

        logger.info(f"[cache] clear: 清理 {count} 条记录")
        return count

    # ---- TASK-CM-08: TTL 过期清理 ----

    def cleanup_expired(self, now: float | None = None) -> int:
        """清理所有过期的缓存条目。

        Args:
            now: 当前时间戳（用于测试时注入）。默认为 time.time()。

        Returns:
            清理的条目数量。
        """
        if now is None:
            now = time.time()
        cutoff = now - self._ttl

        conn = sqlite3.connect(str(self._db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT cache_key, file_path FROM cache_index WHERE created_at < ?", (cutoff,))
        rows = cursor.fetchall()
        count = 0
        for key, file_path in rows:
            fp = Path(file_path)
            try:
                fp.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning(f"[cache] cleanup_expired 删除文件失败: {exc}")
            cursor.execute("DELETE FROM cache_index WHERE cache_key = ?", (key,))
            count += 1

        conn.commit()
        conn.close()
        logger.info(f"[cache] cleanup_expired: 清理 {count} 条过期记录，耗时 {time.time() - now:.3f}s")
        return count

    # ---- TASK-CM-10: 组合清理 ----

    def cleanup(self, force: bool = False) -> dict:
        """组合执行：TTL 过期清理 + 孤立文件清理 + 大小检查。

        Args:
            force: 为 True 时跳过大小限制检查直接清理。

        Returns:
            {"expired_count": N, "orphan_count": M, "total_size_bytes": X}
        """
        expired_count = self.cleanup_expired()
        orphan_count = self._cleanup_orphans()

        stats = self.get_stats()
        return {
            "expired_count": expired_count,
            "orphan_count": orphan_count,
            "total_size_bytes": stats["total_size_bytes"],
        }

    def _cleanup_orphans(self) -> int:
        """清理索引中不存在但文件系统中存在的 .json 文件。

        Returns:
            清理的孤立文件数量。
        """
        conn = sqlite3.connect(str(self._db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT file_path FROM cache_index")
        indexed_paths = {row[0] for row in cursor.fetchall()}
        conn.close()

        orphan_count = 0
        if self._objects_dir.exists():
            for fpath in self._objects_dir.iterdir():
                if fpath.suffix == ".json" and str(fpath) not in indexed_paths:
                    try:
                        fpath.unlink()
                        orphan_count += 1
                    except OSError:
                        pass

        logger.info(f"[cache] cleanup_orphans: 清理 {orphan_count} 个孤立文件")
        return orphan_count

    # ---- TASK-CM-11: 缓存统计增强 ----

    def get_stats(self) -> dict:
        """返回详细的缓存统计信息。

        包含：命中率、TTL 分布、平均年龄、孤立文件检测。
        不包含任何缓存内容。
        """
        conn = sqlite3.connect(str(self._db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*), COALESCE(SUM(file_size), 0) FROM cache_index")
        count, total_size = cursor.fetchone()

        # 近期条目
        cursor.execute("SELECT COUNT(*) FROM cache_index WHERE created_at > ?", (time.time() - 86400,))
        recent = cursor.fetchone()[0]

        # 过期条目数
        cutoff = time.time() - self._ttl
        cursor.execute("SELECT COUNT(*) FROM cache_index WHERE created_at < ?", (cutoff,))
        expired = cursor.fetchone()[0]

        # 平均年龄
        cursor.execute("SELECT AVG(?" " - created_at) FROM cache_index", (time.time(),))
        avg_age = cursor.fetchone()[0] or 0.0

        # TTL 分布
        now = time.time()
        one_hour = 3600
        one_day = 86400
        seven_days = 604800

        cursor.execute("SELECT COUNT(*) FROM cache_index WHERE ? - created_at < ?", (now, one_hour))
        lt_1h = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM cache_index WHERE ? - created_at >= ? AND ? - created_at < ?",
            (now, one_hour, now, one_day),
        )
        h1_to_24 = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM cache_index WHERE ? - created_at >= ? AND ? - created_at < ?",
            (now, one_day, now, seven_days),
        )
        d1_to_7 = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM cache_index WHERE ? - created_at >= ?",
            (now, seven_days),
        )
        gt_7d = cursor.fetchone()[0]

        conn.close()

        total_requests = self._hits + self._misses
        hit_rate = self._hits / total_requests if total_requests > 0 else None

        orphan_count = self._count_orphans()

        return {
            "entries": count,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "recent_entries_24h": recent,
            "hit_count": self._hits,
            "miss_count": self._misses,
            "hit_rate": hit_rate,
            "expired_count": expired,
            "orphan_count": orphan_count,
            "avg_age_seconds": round(avg_age, 2),
            "ttl_distribution": {
                "<1h": lt_1h,
                "1h-24h": h1_to_24,
                "1d-7d": d1_to_7,
                ">7d": gt_7d,
            },
        }

    def get_size(self) -> int:
        """获取缓存大小（字节）。"""
        stats = self.get_stats()
        return stats["total_size_bytes"]

    # --- 内部方法 ---

    def _update_last_accessed(self, key: str):
        """更新最后访问时间（TASK-CM-07）。"""
        conn = sqlite3.connect(str(self._db_path))
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE cache_index SET last_accessed_at = ? WHERE cache_key = ?",
            (time.time(), key),
        )
        conn.commit()
        conn.close()

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
        """按 LRU 清理超过大小限制的缓存（TASK-CM-07：使用 last_accessed_at）。"""
        max_bytes = self._max_size_gb * 1024 * 1024 * 1024
        conn = sqlite3.connect(str(self._db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT SUM(file_size) FROM cache_index")
        total = cursor.fetchone()[0] or 0

        while total > max_bytes:
            # TASK-CM-07: 按 last_accessed_at 升序淘汰最旧项
            cursor.execute("SELECT cache_key, file_size FROM cache_index ORDER BY last_accessed_at ASC LIMIT 1")
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

    def _count_orphans(self) -> int:
        """统计孤立文件数量（不删除）。"""
        conn = sqlite3.connect(str(self._db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT file_path FROM cache_index")
        indexed_paths = {row[0] for row in cursor.fetchall()}
        conn.close()

        orphan_count = 0
        if self._objects_dir.exists():
            for fpath in self._objects_dir.iterdir():
                if fpath.suffix == ".json" and str(fpath) not in indexed_paths:
                    orphan_count += 1
        return orphan_count
