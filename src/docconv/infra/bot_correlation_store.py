"""Bot 任务关联存储（bot_correlations 表）。

使用 SQLite 存储 job_id 与平台消息元数据的关联关系，
用于终态结果回传时查询目标平台会话。
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from docconv.integrations.common import BotJobCorrelation

logger = logging.getLogger(__name__)


# 表创建 DDL
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS bot_correlations (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    external_message_id TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    sender_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

_CREATE_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_job_id ON bot_correlations(job_id);",
    "CREATE INDEX IF NOT EXISTS idx_platform ON bot_correlations(platform);",
    "CREATE INDEX IF NOT EXISTS idx_chat_id ON bot_correlations(chat_id);",
]


class BotCorrelationStore:
    """bot_correlations 表的 CRUD 操作。

    提供：
    - create_correlation: 创建关联记录
    - get_by_job_id: 根据 job_id 查询关联的平台回传信息
    - get_by_chat_id: 根据 chat_id 查询关联记录
    """

    def __init__(self, db_path: str = ""):
        """初始化。

        Args:
            db_path: SQLite 数据库文件路径，不提供则使用内存数据库
        """
        if db_path:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(db_path)
        else:
            self._db = sqlite3.connect(":memory:")

        self._db.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        """创建表和索引。"""
        cursor = self._db.cursor()
        cursor.execute(_CREATE_TABLE_SQL)
        for sql in _CREATE_INDEXES_SQL:
            cursor.execute(sql)
        self._db.commit()

    def create_correlation(self, correlation: BotJobCorrelation) -> BotJobCorrelation:
        """创建关联记录。

        Args:
            correlation: BotJobCorrelation 实例

        Returns:
            已保存的 BotJobCorrelation（含生成的 id 和时间戳）
        """
        now = datetime.now(timezone.utc).isoformat()
        import uuid

        if not correlation.id:
            correlation.id = f"corr_{uuid.uuid4().hex[:12]}"
        if not correlation.created_at:
            correlation.created_at = now
        if not correlation.updated_at:
            correlation.updated_at = now

        self._db.execute(
            """INSERT INTO bot_correlations
               (id, job_id, platform, external_message_id, chat_id, sender_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                correlation.id,
                correlation.job_id,
                correlation.platform,
                correlation.external_message_id,
                correlation.chat_id,
                correlation.sender_id,
                correlation.created_at,
                correlation.updated_at,
            ),
        )
        self._db.commit()
        logger.debug("Bot 关联已创建: job_id=%s, platform=%s", correlation.job_id, correlation.platform)
        return correlation

    def get_by_job_id(self, job_id: str) -> list[BotJobCorrelation]:
        """根据 job_id 查询关联的平台回传信息。

        Args:
            job_id: 任务 ID

        Returns:
            BotJobCorrelation 列表
        """
        cursor = self._db.execute(
            "SELECT * FROM bot_correlations WHERE job_id = ?", (job_id,),
        )
        return [self._row_to_correlation(row) for row in cursor.fetchall()]

    def get_by_chat_id(self, chat_id: str) -> list[BotJobCorrelation]:
        """根据 chat_id 查询关联记录。

        Args:
            chat_id: 会话 ID

        Returns:
            BotJobCorrelation 列表
        """
        cursor = self._db.execute(
            "SELECT * FROM bot_correlations WHERE chat_id = ?", (chat_id,),
        )
        return [self._row_to_correlation(row) for row in cursor.fetchall()]

    def get_by_platform_and_external_id(
        self, platform: str, external_message_id: str,
    ) -> BotJobCorrelation | None:
        """根据平台和外部消息 ID 查询关联记录。

        Args:
            platform: 平台标识
            external_message_id: 平台消息 ID

        Returns:
            BotJobCorrelation 或 None
        """
        cursor = self._db.execute(
            "SELECT * FROM bot_correlations WHERE platform = ? AND external_message_id = ?",
            (platform, external_message_id),
        )
        row = cursor.fetchone()
        if row:
            return self._row_to_correlation(row)
        return None

    def update_job_id(self, correlation_id: str, job_id: str) -> None:
        """更新关联记录的 job_id。

        Args:
            correlation_id: 关联记录 ID
            job_id: 新的任务 ID
        """
        now = datetime.now(timezone.utc).isoformat()
        self._db.execute(
            "UPDATE bot_correlations SET job_id = ?, updated_at = ? WHERE id = ?",
            (job_id, now, correlation_id),
        )
        self._db.commit()

    def delete(self, correlation_id: str) -> bool:
        """删除关联记录。

        Args:
            correlation_id: 关联记录 ID

        Returns:
            True 表示删除成功，False 表示记录不存在
        """
        cursor = self._db.execute(
            "DELETE FROM bot_correlations WHERE id = ?", (correlation_id,),
        )
        self._db.commit()
        return cursor.rowcount > 0

    def close(self) -> None:
        """关闭数据库连接。"""
        self._db.close()

    @staticmethod
    def _row_to_correlation(row: sqlite3.Row) -> BotJobCorrelation:
        """将 SQLite 行转换为 BotJobCorrelation。"""
        return BotJobCorrelation(
            id=row["id"],
            job_id=row["job_id"],
            platform=row["platform"],
            external_message_id=row["external_message_id"],
            chat_id=row["chat_id"],
            sender_id=row["sender_id"] or "",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
