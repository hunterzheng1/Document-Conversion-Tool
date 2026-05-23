"""状态管理器：管理转换任务状态和 per-page 状态机。"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


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

    @property
    def progress(self) -> float:
        if self.total_pages == 0:
            return 0.0
        return len(self.completed_pages) / self.total_pages

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
    """管理转换任务的状态持久化。"""

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self._state_dir = Path(cfg.get("state_dir", ".state/docconv"))
        self._state_dir.mkdir(parents=True, exist_ok=True)

    def _state_file(self, file_path: str) -> Path:
        key = file_path.replace(os.sep, "_").replace(":", "")
        return self._state_dir / f"{key}.json"

    def load(self, file_path: str) -> ConversionState:
        """加载转换状态。"""
        state_file = self._state_file(file_path)
        if state_file.exists():
            with open(state_file) as f:
                data = json.load(f)
            state = ConversionState(**data)
            # 应用状态恢复规则
            self._apply_recovery_rules(state)
            return state
        state = ConversionState(file_path=file_path, started_at=time.time())
        return state

    def save(self, state: ConversionState) -> None:
        """保存转换状态（原子写入）。"""
        state.updated_at = time.time()
        state_file = self._state_file(state.file_path)
        tmp_file = state_file.with_suffix(".tmp")

        with open(tmp_file, "w") as f:
            json.dump(asdict(state), f, ensure_ascii=False, indent=2)

        os.replace(tmp_file, state_file)

    def delete(self, file_path: str) -> None:
        """删除转换状态。"""
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
        """获取恢复策略：{page_num: should_process}。"""
        result = {}
        for page_num in range(state.total_pages):
            page_info = state.get_page_status(page_num)
            if page_info.status == PageStatus.COMPLETED:
                # 检查 artifact 是否存在
                if page_info.artifact and not os.path.exists(page_info.artifact):
                    # artifact 丢失，回退为 pending
                    state.set_page_status(page_num, PageStatus.PENDING)
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

    # --- 内部方法 ---

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
