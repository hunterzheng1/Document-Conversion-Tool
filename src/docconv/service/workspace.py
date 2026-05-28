"""JobWorkspace：为每个 job 创建隔离的工作区目录。"""

from __future__ import annotations

import shutil
from pathlib import Path

from .job_models import JobRecord, JobStatus
from .job_store import SQLiteJobStore


# 允许的子目录
_ALLOWED_SUBDIRS = frozenset({"input", "output", "state", "tmp"})


class JobWorkspace:
    """Job 工作区路径隔离。

    结构:
        {storage_root}/jobs/{job_id}/
            input/    - 输入文件副本
            output/   - result.md / report.md
            state/    - 转换状态
            tmp/      - 临时文件
    """

    def __init__(self, job_id: str, storage_root: str | Path):
        """初始化工作区并创建全部子目录。

        Args:
            job_id: 任务 ID
            storage_root: 存储根目录

        Raises:
            ValueError: job_id 包含路径穿越字符
        """
        self._job_id = job_id
        self._storage_root = Path(storage_root).resolve()
        self._workspace_root = self._storage_root / "jobs" / job_id

        # 安全检查：job_id 不能包含路径穿越
        if ".." in job_id or "/" in job_id or "\\" in job_id:
            raise ValueError(
                f"job_id 包含非法字符: {job_id}"
            )

        # 创建四个子目录
        for subdir in _ALLOWED_SUBDIRS:
            (self._workspace_root / subdir).mkdir(parents=True, exist_ok=True)

    # ---- 属性 ----

    @property
    def workspace_root(self) -> Path:
        """工作区根目录。"""
        return self._workspace_root

    @property
    def input_path(self) -> Path:
        """input 子目录。"""
        return self._workspace_root / "input"

    @property
    def output_path(self) -> Path:
        """output 子目录。"""
        return self._workspace_root / "output"

    @property
    def state_path(self) -> Path:
        """state 子目录。"""
        return self._workspace_root / "state"

    @property
    def tmp_path(self) -> Path:
        """tmp 子目录。"""
        return self._workspace_root / "tmp"

    # ---- 公共方法 ----

    def resolve(self, subdir: str, filename: str) -> Path:
        """生成安全的子目录路径。

        Args:
            subdir: 子目录名，必须是 input/output/state/tmp 之一
            filename: 文件名（可包含子目录，但不能穿越）

        Returns:
            绝对路径

        Raises:
            ValueError: subdir 不合法，或解析后路径不在 workspace 内
        """
        if subdir not in _ALLOWED_SUBDIRS:
            raise ValueError(
                f"非法的子目录 '{subdir}'，允许: {sorted(_ALLOWED_SUBDIRS)}"
            )

        # 使用纯字符串拼接防止路径穿越
        target = (self._workspace_root / subdir / filename).resolve()

        # 确保结果在 workspace 根目录内
        if not str(target).startswith(str(self._workspace_root)):
            raise ValueError(
                f"路径穿越检测: 路径 '{target}' 超出工作区范围"
            )

        return target

    def cleanup(self) -> None:
        """递归删除整个工作区目录（幂等）。"""
        if self._workspace_root.exists():
            shutil.rmtree(self._workspace_root)

    # ---- 静态工具方法 ----

    @staticmethod
    def get_expired_job_ids(
        store: SQLiteJobStore, now: str | None = None
    ) -> list[str]:
        """查询已过期的 job ID 列表。

        Args:
            store: SQLiteJobStore 实例
            now: ISO 时间戳，默认当前 UTC 时间

        Returns:
            过期 job ID 列表
        """
        expired_records = store.list_expired(now)
        return [r.job_id for r in expired_records]
