"""SQLite 状态仓库：页面级转换状态的持久化 CRUD。

本模块提供 `SQLiteStateRepository`，用于在服务模式下
将每页转换进度写入 SQLite `job_progress` 表。
与 `SQLiteJobStore`（存储 job 元数据）互补，
本仓库仅存储页面级转换状态（页号、状态、Markdown、错误）。

包含数据库迁移框架：通过 `schema_migrations` 表记录版本，
支持未来 schema 升级。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# 常量与类型
# ---------------------------------------------------------------------------

_DB_FILENAME = "state.db"
_TABLE_NAME = "job_progress"
_MIGRATION_TABLE = "schema_migrations"
_CURRENT_SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# SQLiteStateRepository
# ---------------------------------------------------------------------------

class SQLiteStateRepository:
    """页面级转换状态的 SQLite 仓库。

    表结构：
        job_progress (
            job_id       TEXT,   -- 所属 job
            page_num     INTEGER,-- 页号（从 1 开始）
            page_status  TEXT,   -- pending|processing|completed|failed
            markdown     TEXT,   -- 页面 Markdown 内容（可为空）
            errors       TEXT,   -- 错误信息 JSON 数组
            created_at   TEXT,   -- ISO 8601
            updated_at   TEXT,   -- ISO 8601
            PRIMARY KEY (job_id, page_num)
        )

    与 SQLiteJobStore 的区别：
    - SQLiteJobStore 存储 job 元数据（状态机、心跳、文件路径等）
    - SQLiteStateRepository 存储页面级转换状态
    """

    def __init__(self, data_dir: str | Path | None = None):
        """初始化仓库。

        Args:
            data_dir: 数据库所在目录，默认 `.data/docconv/state`
        """
        if data_dir is None:
            data_dir = Path(".data/docconv/state")
        self._db_path = Path(data_dir) / _DB_FILENAME
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    # ---- 内部方法 ----

    def _get_conn(self) -> sqlite3.Connection:
        """获取一个独立的连接（线程安全模式）。"""
        conn = sqlite3.connect(
            str(self._db_path),
            timeout=30,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @contextmanager
    def _transaction(self):
        """开启一个 BEGIN IMMEDIATE 事务。"""
        conn = self._get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        """幂等初始化 job_progress 表、索引和迁移表。"""
        with self._transaction() as conn:
            conn.executescript(f"""
                CREATE TABLE IF NOT EXISTS {_TABLE_NAME} (
                    job_id       TEXT    NOT NULL,
                    page_num     INTEGER NOT NULL,
                    page_status  TEXT    NOT NULL DEFAULT 'pending',
                    markdown     TEXT    DEFAULT '',
                    errors       TEXT    DEFAULT '[]',
                    created_at   TEXT    NOT NULL,
                    updated_at   TEXT    NOT NULL,
                    PRIMARY KEY  (job_id, page_num)
                );

                CREATE INDEX IF NOT EXISTS idx_job_status
                    ON {_TABLE_NAME} (job_id, page_status);
                CREATE INDEX IF NOT EXISTS idx_job_updated
                    ON {_TABLE_NAME} (job_id, updated_at);
            """)
        # 初始化迁移表并记录当前版本
        self._init_migrations()

    def _now_iso(self) -> str:
        """返回当前 UTC ISO 8601 时间戳。"""
        return datetime.now(timezone.utc).isoformat()

    # ---- CRUD ----

    def upsert_page(
        self,
        job_id: str,
        page_num: int,
        status: str,
        markdown: str = "",
        errors: list[str] | None = None,
    ) -> None:
        """插入或更新单页状态（原子操作）。

        Args:
            job_id: 任务 ID
            page_num: 页号（从 1 开始）
            status: 页面状态 (pending/processing/completed/failed)
            markdown: 页面 Markdown 内容
            errors: 错误信息列表
        """
        now = self._now_iso()
        errors_json = json.dumps(errors or [], ensure_ascii=False)

        with self._lock:
            with self._transaction() as conn:
                # 先检查是否存在
                cursor = conn.execute(
                    f"SELECT 1 FROM {_TABLE_NAME} WHERE job_id = ? AND page_num = ?",
                    (job_id, page_num),
                )
                exists = cursor.fetchone() is not None

                if exists:
                    conn.execute(
                        f"""UPDATE {_TABLE_NAME}
                            SET page_status = ?, markdown = ?, errors = ?, updated_at = ?
                            WHERE job_id = ? AND page_num = ?""",
                        (status, markdown, errors_json, now, job_id, page_num),
                    )
                else:
                    conn.execute(
                        f"""INSERT INTO {_TABLE_NAME}
                            (job_id, page_num, page_status, markdown, errors, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (job_id, page_num, status, markdown, errors_json, now, now),
                    )

    def get_pages(self, job_id: str) -> list[dict[str, Any]]:
        """获取指定 job 的所有页面状态。

        Args:
            job_id: 任务 ID

        Returns:
            页面状态列表，按 page_num 升序排列
        """
        with self._transaction() as conn:
            cursor = conn.execute(
                f"""SELECT job_id, page_num, page_status, markdown, errors,
                           created_at, updated_at
                    FROM {_TABLE_NAME}
                    WHERE job_id = ?
                    ORDER BY page_num ASC""",
                (job_id,),
            )
            rows = []
            for row in cursor.fetchall():
                data = dict(row)
                # 反序列化 errors JSON
                try:
                    data["errors"] = json.loads(data.get("errors", "[]"))
                except (json.JSONDecodeError, TypeError):
                    data["errors"] = []
                rows.append(data)
            return rows

    def get_page(self, job_id: str, page_num: int) -> dict[str, Any] | None:
        """获取指定页面状态。

        Args:
            job_id: 任务 ID
            page_num: 页号

        Returns:
            页面状态字典，不存在时返回 None
        """
        with self._transaction() as conn:
            cursor = conn.execute(
                f"""SELECT job_id, page_num, page_status, markdown, errors,
                           created_at, updated_at
                    FROM {_TABLE_NAME}
                    WHERE job_id = ? AND page_num = ?""",
                (job_id, page_num),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            data = dict(row)
            try:
                data["errors"] = json.loads(data.get("errors", "[]"))
            except (json.JSONDecodeError, TypeError):
                data["errors"] = []
            return data

    def get_progress_summary(self, job_id: str) -> dict[str, Any]:
        """获取 job 的进度摘要。

        Args:
            job_id: 任务 ID

        Returns:
            进度摘要字典，包含 total/completed/failed/pending/processing 计数
        """
        with self._transaction() as conn:
            cursor = conn.execute(
                f"""SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN page_status = 'completed' THEN 1 ELSE 0 END) as completed,
                        SUM(CASE WHEN page_status = 'failed' THEN 1 ELSE 0 END) as failed,
                        SUM(CASE WHEN page_status = 'pending' THEN 1 ELSE 0 END) as pending,
                        SUM(CASE WHEN page_status = 'processing' THEN 1 ELSE 0 END) as processing
                    FROM {_TABLE_NAME}
                    WHERE job_id = ?""",
                (job_id,),
            )
            row = cursor.fetchone()
            if row is None or row["total"] == 0:
                return {
                    "job_id": job_id,
                    "total": 0,
                    "completed": 0,
                    "failed": 0,
                    "pending": 0,
                    "processing": 0,
                    "progress": 0.0,
                }
            total = row["total"]
            completed = row["completed"]
            return {
                "job_id": job_id,
                "total": total,
                "completed": completed,
                "failed": row["failed"],
                "pending": row["pending"],
                "processing": row["processing"],
                "progress": completed / total if total > 0 else 0.0,
            }

    def delete_job(self, job_id: str) -> int:
        """删除指定 job 的所有页面状态。

        Args:
            job_id: 任务 ID

        Returns:
            被删除的行数
        """
        with self._lock:
            with self._transaction() as conn:
                cursor = conn.execute(
                    f"DELETE FROM {_TABLE_NAME} WHERE job_id = ?",
                    (job_id,),
                )
                return cursor.rowcount

    def delete_page(self, job_id: str, page_num: int) -> bool:
        """删除指定页面状态。

        Args:
            job_id: 任务 ID
            page_num: 页号

        Returns:
            是否成功删除（页面存在）
        """
        with self._lock:
            with self._transaction() as conn:
                cursor = conn.execute(
                    f"DELETE FROM {_TABLE_NAME} WHERE job_id = ? AND page_num = ?",
                    (job_id, page_num),
                )
                return cursor.rowcount > 0

    def save_or_update(
        self,
        job_id: str,
        page_num: int,
        status: str,
        markdown: str = "",
        errors: list[str] | None = None,
    ) -> None:
        """插入或更新单页状态（INSERT OR REPLACE 语义）。

        与 `upsert_page` 功能相同，但明确表达 save_or_update 的
        意图，用于并发安全的原子操作。

        Args:
            job_id: 任务 ID
            page_num: 页号
            status: 页面状态
            markdown: 页面 Markdown 内容
            errors: 错误信息列表
        """
        self.upsert_page(job_id, page_num, status, markdown, errors)

    def atomic_claim_progress(
        self, job_id: str
    ) -> dict[str, Any]:
        """原子读取并锁定当前进度，防止并发写入冲突。

        使用 BEGIN IMMEDIATE 事务确保在读取期间其他写入被阻塞。

        Args:
            job_id: 任务 ID

        Returns:
            进度摘要字典，包含 total/completed/failed/pending/processing
        """
        return self.get_progress_summary(job_id)
    def get_pages_by_status(
        self, job_id: str, status: str
    ) -> list[dict[str, Any]]:
        """按状态筛选页面。

        Args:
            job_id: 任务 ID
            status: 页面状态

        Returns:
            符合条件的页面列表
        """
        with self._transaction() as conn:
            cursor = conn.execute(
                f"""SELECT job_id, page_num, page_status, markdown, errors,
                           created_at, updated_at
                    FROM {_TABLE_NAME}
                    WHERE job_id = ? AND page_status = ?
                    ORDER BY page_num ASC""",
                (job_id, status),
            )
            rows = []
            for row in cursor.fetchall():
                data = dict(row)
                try:
                    data["errors"] = json.loads(data.get("errors", "[]"))
                except (json.JSONDecodeError, TypeError):
                    data["errors"] = []
                rows.append(data)
            return rows

    # ---- 迁移框架 ----

    def _init_migrations(self) -> None:
        """幂等初始化 schema_migrations 表。"""
        with self._transaction() as conn:
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {_MIGRATION_TABLE} (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
            """)
            # 如果没有任何迁移记录，记录当前版本
            cursor = conn.execute(
                f"SELECT MAX(version) as v FROM {_MIGRATION_TABLE}"
            )
            row = cursor.fetchone()
            if row["v"] is None:
                conn.execute(
                    f"INSERT INTO {_MIGRATION_TABLE} (version, applied_at) VALUES (?, ?)",
                    (_CURRENT_SCHEMA_VERSION, self._now_iso()),
                )

    def get_schema_version(self) -> int:
        """获取当前数据库 schema 版本。

        Returns:
            当前版本号，无记录时返回 0
        """
        with self._transaction() as conn:
            cursor = conn.execute(
                f"SELECT MAX(version) as v FROM {_MIGRATION_TABLE}"
            )
            row = cursor.fetchone()
            return row["v"] if row["v"] is not None else 0

    def migrate(self, to_version: int | None = None) -> dict[str, Any]:
        """执行数据库迁移。

        Args:
            to_version: 目标版本，None 表示升级到最新版本

        Returns:
            迁移报告，包含 from_version、to_version、applied_migrations

        Raises:
            StateFormatError: 向下不兼容时抛出
        """
        # 延迟导入避免循环
        from docconv.core.exceptions import StateFormatError

        current = self.get_schema_version()
        target = to_version if to_version is not None else _CURRENT_SCHEMA_VERSION

        if target < current:
            raise StateFormatError(
                f"向下不兼容：当前版本 {current}，目标版本 {target}"
            )

        if target == current:
            return {
                "from_version": current,
                "to_version": current,
                "applied_migrations": [],
                "status": "up-to-date",
            }

        # 迁移映射（预留扩展点）
        migrations = {
            1: self._migrate_to_v1,
            # 未来版本在此添加
        }

        applied = []
        for v in range(current + 1, target + 1):
            if v not in migrations:
                raise StateFormatError(f"未定义迁移版本 {v}")
            migrations[v]()
            applied.append(v)
            # 记录版本
            with self._lock:
                with self._transaction() as conn:
                    conn.execute(
                        f"INSERT OR REPLACE INTO {_MIGRATION_TABLE} (version, applied_at) VALUES (?, ?)",
                        (v, self._now_iso()),
                    )

        return {
            "from_version": current,
            "to_version": target,
            "applied_migrations": applied,
            "status": "success",
        }

    def _migrate_to_v1(self) -> None:
        """迁移到 v1：初始化基础表（幂等操作）。"""
        self._init_db()
