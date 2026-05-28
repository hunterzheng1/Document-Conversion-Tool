"""SQLite Job 存储：原子 CRUD 与 claim 操作。"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .job_models import JobRecord, JobStatus


# ---------------------------------------------------------------------------
# SQLiteJobStore
# ---------------------------------------------------------------------------

class SQLiteJobStore:
    """SQLite job 元数据读写，支持原子 claim 和事务。"""

    # 需要 JSON 序列化的字段
    _JSON_FIELDS = {"options_json", "progress_json"}

    def __init__(self, db_path: str | Path | None = None):
        """初始化。

        Args:
            db_path: SQLite 数据库文件路径，默认 `.data/docconv/job_store.sqlite3`
        """
        if db_path is None:
            db_path = Path(".data/docconv/job_store.sqlite3")
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    # ---- 内部方法 ----

    def _get_conn(self) -> sqlite3.Connection:
        """获取一个非共享连接（线程安全模式）。"""
        conn = sqlite3.connect(
            str(self._db_path),
            timeout=30,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
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
        """幂等初始化表结构和索引。"""
        with self._transaction() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id          TEXT    PRIMARY KEY,
                    source          TEXT    NOT NULL,
                    status          TEXT    NOT NULL DEFAULT 'queued',
                    original_filename TEXT  NOT NULL,
                    input_path      TEXT    NOT NULL,
                    output_path     TEXT    DEFAULT NULL,
                    report_path     TEXT    DEFAULT NULL,
                    instruction     TEXT    DEFAULT '',
                    options_json    TEXT    DEFAULT '{}',
                    progress_json   TEXT    DEFAULT '{}',
                    error_type      TEXT    DEFAULT NULL,
                    error_message   TEXT    DEFAULT NULL,
                    locked_by       TEXT    DEFAULT NULL,
                    heartbeat_at    TEXT    DEFAULT NULL,
                    created_at      TEXT    NOT NULL,
                    updated_at      TEXT    NOT NULL,
                    expires_at      TEXT    NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_source   ON jobs(source);
                CREATE INDEX IF NOT EXISTS idx_status   ON jobs(status);
                CREATE INDEX IF NOT EXISTS idx_locked_by ON jobs(locked_by);
                CREATE INDEX IF NOT EXISTS idx_created  ON jobs(created_at);
                CREATE INDEX IF NOT EXISTS idx_expires  ON jobs(expires_at);
            """)

    def _row_to_record(self, row: sqlite3.Row) -> JobRecord:
        """将 sqlite3.Row 转为 JobRecord。"""
        data = dict(row)
        for json_field in self._JSON_FIELDS:
            val = data.get(json_field)
            if isinstance(val, str):
                try:
                    data[json_field] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    data[json_field] = {}
        # 将空字符串转为空字符串保持兼容
        for key in ("locked_by", "heartbeat_at", "error_type", "error_message"):
            if data.get(key) is None:
                data[key] = ""
        return JobRecord.from_dict(data)

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    # ---- 公共 CRUD ----

    def insert(self, record: JobRecord) -> str:
        """插入一条 job 记录。

        Args:
            record: JobRecord 实例

        Returns:
            job_id

        Raises:
            ServiceError: 插入失败时
        """
        from .job_models import ServiceError, ErrorCodes
        now = self._now_iso()
        if not record.created_at:
            record.created_at = now
        if not record.updated_at:
            record.updated_at = now
        if not record.expires_at:
            record.expires_at = now  # 调用方应自行设置 expires_at

        try:
            with self._transaction() as conn:
                conn.execute(
                    """INSERT INTO jobs (
                        job_id, source, status, original_filename,
                        input_path, output_path, report_path, instruction,
                        options_json, progress_json, error_type, error_message,
                        locked_by, heartbeat_at, created_at, updated_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        record.job_id,
                        record.source,
                        record.status,
                        record.original_filename,
                        record.input_path,
                        record.output_path or None,
                        record.report_path or None,
                        record.instruction,
                        json.dumps(record.options_json),
                        json.dumps(record.progress_json),
                        record.error_type or None,
                        record.error_message or None,
                        record.locked_by or None,
                        record.heartbeat_at or None,
                        record.created_at,
                        record.updated_at,
                        record.expires_at,
                    ),
                )
            return record.job_id
        except sqlite3.IntegrityError as exc:
            raise ServiceError(
                ErrorCodes.SVC5001,
                f"job 插入失败 (重复?): {exc}",
            )

    def get(self, job_id: str) -> JobRecord | None:
        """查询单条 job 记录。

        Args:
            job_id: 任务 ID

        Returns:
            JobRecord 或 None（不存在时）
        """
        with self._transaction() as conn:
            cursor = conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?",
                (job_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return self._row_to_record(row)

    def count_by_status(self, status: str) -> int:
        """统计指定状态的 job 数量。

        Args:
            status: 状态值

        Returns:
            数量
        """
        with self._transaction() as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE status = ?",
                (status,),
            )
            return cursor.fetchone()[0]

    def list_by_status(
        self, status: str, limit: int = 100
    ) -> list[JobRecord]:
        """列出指定状态的 job 记录。

        Args:
            status: 状态值
            limit: 返回上限

        Returns:
            JobRecord 列表
        """
        with self._transaction() as conn:
            cursor = conn.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY created_at LIMIT ?",
                (status, limit),
            )
            return [self._row_to_record(row) for row in cursor.fetchall()]

    def update(self, job_id: str, fields: dict[str, Any]) -> None:
        """部分字段更新，自动更新 updated_at。

        Args:
            job_id: 任务 ID
            fields: 要更新的字段映射

        Raises:
            ServiceError: job 不存在或更新失败
        """
        from .job_models import ServiceError, ErrorCodes

        # 自动设置 updated_at
        fields = dict(fields)
        fields["updated_at"] = self._now_iso()

        # JSON 字段需要序列化
        for json_field in self._JSON_FIELDS:
            if json_field in fields and isinstance(fields[json_field], dict):
                fields[json_field] = json.dumps(fields[json_field])

        # 构建 SET 子句
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [job_id]

        with self._transaction() as conn:
            cursor = conn.execute(
                f"UPDATE jobs SET {set_clause} WHERE job_id = ?",
                values,
            )
            if cursor.rowcount == 0:
                raise ServiceError(
                    ErrorCodes.SVC2001,
                    f"job 不存在，无法更新: {job_id}",
                )

    def delete(self, job_id: str) -> None:
        """删除一条 job 记录。

        Args:
            job_id: 任务 ID

        Raises:
            ServiceError: job 不存在
        """
        from .job_models import ServiceError, ErrorCodes

        with self._transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM jobs WHERE job_id = ?",
                (job_id,),
            )
            if cursor.rowcount == 0:
                raise ServiceError(
                    ErrorCodes.SVC2001,
                    f"job 不存在，无法删除: {job_id}",
                )

    # ---- 原子 claim ----

    def claim_next_job(self, worker_id: str) -> JobRecord | None:
        """原子领取下一个 queued 任务。

        使用单事务更新 status='queued' 且 locked_by IS NULL 的最早任务，
        设置 status='running'、locked_by=worker_id、heartbeat_at=now。

        Args:
            worker_id: Worker 标识

        Returns:
            更新后的 JobRecord；无可用任务时返回 None
        """
        now = self._now_iso()
        with self._transaction() as conn:
            # Step 1: Find the oldest queued job (SQLite UPDATE doesn't support ORDER BY)
            cursor = conn.execute(
                """SELECT job_id FROM jobs
                   WHERE status = 'queued' AND locked_by IS NULL
                   ORDER BY created_at
                   LIMIT 1""",
            )
            row = cursor.fetchone()
            if row is None:
                return None

            target_id = row[0]

            # Step 2: Atomically update that specific job
            conn.execute(
                """UPDATE jobs SET
                       status = 'running',
                       locked_by = ?,
                       heartbeat_at = ?,
                       updated_at = ?
                   WHERE job_id = ?
                     AND status = 'queued'
                     AND locked_by IS NULL""",
                (worker_id, now, now, target_id),
            )
            changes = conn.execute("SELECT changes()").fetchone()[0]
            if changes != 1:
                # Another worker may have claimed it between steps 1 and 2
                return None

            # Step 3: Return the claimed record
            cursor = conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?",
                (target_id,),
            )
            claimed_row = cursor.fetchone()
            if claimed_row is None:
                return None
            return self._row_to_record(claimed_row)

    # ---- 查询过期 job ----

    def list_expired(self, now: str | None = None) -> list[JobRecord]:
        """查询已过期的 job。

        Args:
            now: ISO 格式时间戳，默认当前 UTC 时间

        Returns:
            过期 job 列表
        """
        if now is None:
            now = self._now_iso()
        with self._transaction() as conn:
            cursor = conn.execute(
                "SELECT * FROM jobs WHERE expires_at < ? AND status NOT IN ('expired') ORDER BY expires_at",
                (now,),
            )
            return [self._row_to_record(row) for row in cursor.fetchall()]

    def mark_expired(self, job_id: str) -> None:
        """标记 job 为 expired。

        Args:
            job_id: 任务 ID
        """
        self.update(job_id, {"status": JobStatus.EXPIRED})

    # ---- 恢复机制 ----

    def list_stale_running(
        self, stale_seconds: int = 600
    ) -> list[JobRecord]:
        """查询 running 且心跳过期的任务（用于重启恢复）。

        Args:
            stale_seconds: 心跳超时秒数

        Returns:
            心跳过期的 running job 列表
        """
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(seconds=stale_seconds)).isoformat()

        with self._transaction() as conn:
            cursor = conn.execute(
                """SELECT * FROM jobs
                   WHERE status = 'running'
                     AND heartbeat_at IS NOT NULL
                     AND heartbeat_at < ?
                   ORDER BY heartbeat_at""",
                (cutoff,),
            )
            return [self._row_to_record(row) for row in cursor.fetchall()]
