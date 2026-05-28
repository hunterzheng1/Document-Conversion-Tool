"""状态管理器：管理转换任务状态和 per-page 状态机。

支持双模式：
- JSON 模式（默认）：每任务一个 JSON 文件，CLI 向后兼容
- SQLite 模式：通过 SQLiteStateRepository 存储页面级状态，服务模式使用
- Auto 模式：自动检测配置，有 job_id 和 state_repo 时用 SQLite，否则 JSON
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# StateConfig：状态管理配置项
# ---------------------------------------------------------------------------

@dataclass
class StateConfig:
    """状态管理配置项（design.md 9.1/9.2 节）。

    支持从 dict 构造函数初始化：
        StateConfig.from_dict({"state_dir": "/path"})
    """
    state_dir: str = ".docconv_state"
    job_state_dir: str = "jobs"
    pages_dir: str = "pages"
    enabled: bool = True
    atomic_write: bool = True
    recover_processing: bool = True
    state_lock_timeout_ms: int = 5000
    atomic_write_retry_interval_ms: int = 100
    recovery_scan_timeout_ms: int = 30000

    @classmethod
    def from_dict(cls, data: dict) -> "StateConfig":
        """从字典构造 StateConfig。"""
        allowed = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in allowed}
        return cls(**filtered)

    @property
    def state_lock_timeout_sec(self) -> float:
        return self.state_lock_timeout_ms / 1000.0

    @property
    def atomic_write_retry_interval_sec(self) -> float:
        return self.atomic_write_retry_interval_ms / 1000.0

    @property
    def recovery_scan_timeout_sec(self) -> float:
        return self.recovery_scan_timeout_ms / 1000.0


# ---------------------------------------------------------------------------
# 页面状态与转换状态
# ---------------------------------------------------------------------------


class PageStatus:
    """页面状态枚举。"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class PageInfo:
    """单页状态信息。"""
    status: str = PageStatus.PENDING
    artifact: str | None = None
    meta: str | None = None
    attempts: int = 0
    error_type: str | None = None


@dataclass
class ConversionState:
    """转换任务状态。"""
    file_path: str = ""
    file_hash: str = ""
    total_pages: int = 0
    pages: dict[int, dict] = field(default_factory=dict)
    completed_pages: list[int] = field(default_factory=list)
    failed_pages: dict[int, str] = field(default_factory=dict)
    status: str = "pending"
    started_at: float = 0.0
    updated_at: float = 0.0
    errors: list[str] = field(default_factory=list)
    # 服务模式扩展字段（向后兼容，CLI 模式下为 None/0）
    job_id: str | None = None
    schema_version: int = 2
    workspace: str | None = None

    @property
    def progress(self) -> float:
        if self.total_pages == 0:
            return 0.0
        return len(self.completed_pages) / self.total_pages

    @property
    def completed_count(self) -> int:
        """已完成页数。"""
        return len(self.completed_pages)

    @property
    def failed_count(self) -> int:
        """失败页数。"""
        return len(self.failed_pages)

    def get_page_status(self, page_num: int) -> PageInfo:
        """获取指定页状态。"""
        if page_num in self.pages:
            data = self.pages[page_num]
            return PageInfo(**data)
        return PageInfo()

    def set_page_status(self, page_num: int, status: str, **kwargs):
        """设置页面状态。"""
        page_info = {
            "status": status,
            "artifact": kwargs.get("artifact"),
            "meta": kwargs.get("meta"),
            "attempts": kwargs.get("attempts", 0),
            "error_type": kwargs.get("error_type"),
        }
        self.pages[page_num] = page_info

    def set_page_processing(self, page_num: int):
        """标记页面为处理中。"""
        current = self.get_page_status(page_num)
        self.set_page_status(page_num, PageStatus.PROCESSING, attempts=current.attempts + 1)

    def set_page_completed(self, page_num: int, artifact_path: str = "", meta_path: str = ""):
        """标记页面为完成。"""
        current = self.get_page_status(page_num)
        self.set_page_status(page_num, PageStatus.COMPLETED,
                             artifact=artifact_path, meta=meta_path,
                             attempts=current.attempts + 1)
        if page_num not in self.completed_pages:
            self.completed_pages.append(page_num)

    def set_page_failed(self, page_num: int, error_type: str = "", attempts: int = 0):
        """标记页面为失败。"""
        self.set_page_status(page_num, PageStatus.FAILED,
                             error_type=error_type, attempts=attempts)
        self.failed_pages[page_num] = error_type


class StateManager:
    """管理转换任务的状态持久化。

    支持三种模式：
    - "json": 使用 JSON 文件存储状态（CLI 向后兼容）
    - "sqlite": 使用 SQLiteStateRepository 存储页面级状态（服务模式）
    - "auto": 自动检测，有 job_id + state_repo 时用 sqlite，否则 json
    """

    # 模式常量
    MODE_JSON = "json"
    MODE_SQLITE = "sqlite"
    MODE_AUTO = "auto"

    def __init__(self, config: dict | None = None, mode: str = "auto"):
        cfg = config or {}
        self._state_dir = Path(cfg.get("state_dir", ".state/docconv"))
        self._state_dir.mkdir(parents=True, exist_ok=True)

        # 服务模式配置
        self._job_id: str | None = cfg.get("job_id")
        self._state_repo = cfg.get("state_repo")  # SQLiteStateRepository 实例

        # 解析模式
        self._mode = self._resolve_mode(mode)

    def _resolve_mode(self, mode: str) -> str:
        """解析最终存储模式。

        Args:
            mode: 用户指定的模式 ("json"|"sqlite"|"auto")

        Returns:
            实际使用的模式
        """
        if mode == self.MODE_JSON:
            return self.MODE_JSON
        if mode == self.MODE_SQLITE:
            return self.MODE_SQLITE
        # auto: 有 state_repo 时用 sqlite，否则 json
        if self._state_repo is not None:
            return self.MODE_SQLITE
        return self.MODE_JSON

    # ---- 路径定位 ----

    def _state_file(self, file_path: str) -> Path:
        """获取 JSON 状态文件路径（仅 JSON 模式使用）。

        Args:
            file_path: 文件路径，用于派生 key

        Returns:
            JSON 状态文件路径
        """
        key = file_path.replace(os.sep, "_").replace(":", "")
        return self._state_dir / f"{key}.json"

    # ---- 公共方法 ----

    def load(self, file_path: str) -> ConversionState:
        """加载转换状态。

        JSON 模式：从 file_path 派生的 JSON 文件加载
        SQLite 模式：从 job_id 加载页面状态并组装 ConversionState

        Args:
            file_path: 文件路径（JSON 模式）或 job_id 标识（SQLite 模式）

        Returns:
            ConversionState 实例
        """
        if self._mode == self.MODE_SQLITE and self._state_repo is not None:
            return self._load_from_sqlite(file_path)
        return self._load_from_json(file_path)

    def _load_from_json(self, file_path: str) -> ConversionState:
        """从 JSON 文件加载状态。"""
        state_file = self._state_file(file_path)
        if state_file.exists():
            with open(state_file) as f:
                data = json.load(f)
            state = ConversionState(**data)
            self._apply_recovery_rules(state)
            return state
        state = ConversionState(file_path=file_path, started_at=time.time())
        return state

    def _load_from_sqlite(self, file_path: str) -> ConversionState:
        """从 SQLite 仓库加载状态。

        参数 file_path 在这里作为 job_id 使用。
        """
        job_id = self._job_id or file_path
        pages = self._state_repo.get_pages(job_id)

        if not pages:
            # 无页面数据，返回空状态
            return ConversionState(
                job_id=job_id,
                started_at=time.time(),
            )

        state = ConversionState(
            job_id=job_id,
            total_pages=len(pages),
        )

        completed = []
        failed = {}

        for page_data in pages:
            page_num = page_data["page_num"]
            status = page_data["page_status"]

            state.set_page_status(
                page_num,
                status,
                artifact=page_data.get("markdown", ""),
                error_type=(page_data.get("errors") or [None])[0]
                if page_data.get("errors") else None,
            )

            if status == PageStatus.COMPLETED:
                completed.append(page_num)
            elif status == PageStatus.FAILED:
                errors = page_data.get("errors", [])
                failed[page_num] = errors[0] if errors else "unknown"

        state.completed_pages = completed
        state.failed_pages = failed
        state.updated_at = time.time()

        self._apply_recovery_rules(state)
        return state

    def save(self, state: ConversionState) -> None:
        """保存转换状态（原子写入）。

        JSON 模式：写 *.tmp 后 os.replace()
        SQLite 模式：同步到 state_repo（页面级 upsert）
        """
        if self._mode == self.MODE_SQLITE and self._state_repo is not None:
            self._save_to_sqlite(state)
            return
        self._save_to_json(state)

    def _save_to_json(self, state: ConversionState) -> None:
        """保存状态到 JSON 文件（原子写入，失败重试 2 次）。"""
        from docconv.core.exceptions import StateWriteError

        state.updated_at = time.time()
        state_file = self._state_file(state.file_path)

        # 确保父目录存在
        state_file.parent.mkdir(parents=True, exist_ok=True)

        tmp_file = state_file.with_suffix(".tmp")

        # 重试策略：100ms, 500ms
        retry_intervals = [0.1, 0.5]
        last_error: Exception | None = None

        for attempt, interval in enumerate([0.0] + retry_intervals):
            if attempt > 0:
                time.sleep(interval)
            try:
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump(asdict(state), f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_file, state_file)
                return
            except Exception as e:
                last_error = e
                logger.warning(
                    "状态写入失败 (attempt=%d, file=%s): %s",
                    attempt + 1, state_file, e,
                )
                # 清理残留临时文件
                if tmp_file.exists():
                    try:
                        tmp_file.unlink()
                    except OSError:
                        pass

        raise StateWriteError(
            f"状态写入失败 (file={state_file}): {last_error}"
        )

    def _save_to_sqlite(self, state: ConversionState) -> None:
        """保存状态到 SQLite 仓库。

        将 ConversionState.pages 中的所有页面状态同步到
        job_progress 表。
        """
        job_id = state.job_id or self._job_id
        if not job_id:
            return

        # 更新每页状态
        for page_num, page_data in state.pages.items():
            status = page_data.get("status", PageStatus.PENDING)
            markdown = page_data.get("artifact") or ""
            error_type = page_data.get("error_type")
            errors = [error_type] if error_type else []

            self._state_repo.upsert_page(
                job_id=job_id,
                page_num=page_num,
                status=status,
                markdown=markdown,
                errors=errors,
            )

    def delete(self, file_path: str) -> None:
        """删除转换状态。"""
        if self._mode == self.MODE_SQLITE and self._state_repo is not None:
            job_id = self._job_id or file_path
            self._state_repo.delete_job(job_id)
            return

        state_file = self._state_file(file_path)
        if state_file.exists():
            state_file.unlink()

    def list_states(self) -> list[ConversionState]:
        """列出所有状态。"""
        states = []
        for f in self._state_dir.glob("*.json"):
            with open(f) as fh:
                data = json.load(fh)
            states.append(ConversionState(**data))
        return states

    def get_resume_pages(self, state: ConversionState) -> dict[int, bool]:
        """获取恢复策略：{page_num: should_process}。

        应用恢复规则：
        1. processing 页面降级为 pending
        2. completed 但 artifact 丢失的页面降级为 pending，记录 warning
        3. completed 且 artifact 存在的页面跳过
        4. failed 页面默认重试
        """
        result = {}
        for page_num in range(state.total_pages):
            page_info = state.get_page_status(page_num)
            if page_info.status == PageStatus.COMPLETED:
                # 检查 artifact 是否存在
                if page_info.artifact and not os.path.exists(page_info.artifact):
                    # artifact 丢失，回退为 pending 并记录 warning
                    state.set_page_status(page_num, PageStatus.PENDING)
                    state.errors.append(
                        f"warning: page {page_num} artifact missing, downgraded to pending"
                    )
                    result[page_num] = True
                else:
                    result[page_num] = False  # 跳过
            elif page_info.status == PageStatus.FAILED:
                result[page_num] = True  # 默认重试
            elif page_info.status == PageStatus.PROCESSING:
                # 异常中断，视为 pending
                state.set_page_status(page_num, PageStatus.PENDING)
                result[page_num] = True
            else:
                result[page_num] = True  # pending
        return result

    # ---- 属性 ----

    @property
    def mode(self) -> str:
        """当前使用的存储模式。"""
        return self._mode

    @property
    def is_service_mode(self) -> bool:
        """是否处于服务模式。"""
        return self._mode == self.MODE_SQLITE

    # ---- 内部方法 ----

    def _apply_recovery_rules(self, state: ConversionState):
        """应用状态恢复规则。"""
        for page_num in list(state.pages.keys()):
            page_info = state.pages[page_num]
            status = page_info.get("status", PageStatus.PENDING)

            # processing 页面视为 pending（异常中断）
            if status == PageStatus.PROCESSING:
                state.pages[page_num]["status"] = PageStatus.PENDING

            # completed 但 artifact 丢失，回退为 pending
            if status == PageStatus.COMPLETED:
                artifact = page_info.get("artifact")
                if artifact and not os.path.exists(artifact):
                    state.pages[page_num]["status"] = PageStatus.PENDING

    # ---- 清理与归档 ----

    def cleanup_completed(self, older_than_days: int = 30) -> int:
        """清理超过指定天数的已完成状态。

        JSON 模式：扫描 state_dir 中的 JSON 文件，
        删除 completed 且 updated_at 超过 older_than_days 的记录。

        Args:
            older_than_days: 超过此天数的记录将被删除

        Returns:
            被清理的记录数
        """
        import math

        cutoff = time.time() - (older_than_days * 86400)
        count = 0

        for f in self._state_dir.glob("*.json"):
            try:
                with open(f) as fh:
                    data = json.load(fh)
                updated = data.get("updated_at", 0)
                status = data.get("status", "")
                if status == "completed" and updated < cutoff:
                    f.unlink()
                    count += 1
                    logger.info(
                        "清理已完成状态: %s (updated_at=%s)",
                        f.name, updated,
                    )
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("清理状态时出错 %s: %s", f, e)

        return count

    def archive_state(
        self, file_path: str, archive_dir: str | Path
    ) -> bool:
        """将指定状态的 state.json 和 pages/ 移动到归档目录。

        Args:
            file_path: 文件路径（用于定位 state）
            archive_dir: 归档目录

        Returns:
            是否成功归档
        """
        import shutil

        archive_dir = Path(archive_dir)
        state_file = self._state_file(file_path)
        key = state_file.stem  # 不带扩展名的文件名
        job_archive = archive_dir / key

        if not state_file.exists():
            return False

        try:
            job_archive.mkdir(parents=True, exist_ok=True)
            # 移动 state.json
            shutil.move(str(state_file), str(job_archive / "state.json"))
            # 移动 pages/ 目录（如果存在）
            pages_dir = self._state_dir / "pages"
            if pages_dir.exists():
                shutil.move(str(pages_dir), str(job_archive / "pages"))
            logger.info("状态已归档: %s -> %s", file_path, job_archive)
            return True
        except Exception as e:
            logger.error("归档失败: %s -> %s: %s", file_path, job_archive, e)
            # 回滚：如果归档目录已创建但失败，清理残留
            if job_archive.exists():
                try:
                    shutil.rmtree(job_archive)
                except OSError:
                    pass
            return False

    def get_state_size(self, file_path: str) -> int:
        """计算 state 占用的磁盘空间（字节）。

        Args:
            file_path: 文件路径

        Returns:
            字节数
        """
        total = 0
        state_file = self._state_file(file_path)
        if state_file.exists():
            total += state_file.stat().st_size
        pages_dir = self._state_dir / "pages"
        if pages_dir.exists():
            for f in pages_dir.rglob("*"):
                if f.is_file():
                    total += f.stat().st_size
        return total
