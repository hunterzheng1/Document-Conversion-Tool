"""状态管理器：管理转换任务状态。"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


@dataclass
class ConversionState:
    """转换任务状态。"""
    file_path: str = ""
    total_pages: int = 0
    completed_pages: list[int] = field(default_factory=list)
    failed_pages: dict[int, str] = field(default_factory=dict)
    status: str = "pending"  # pending, running, paused, completed, failed
    started_at: float = 0.0
    updated_at: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def progress(self) -> float:
        if self.total_pages == 0:
            return 0.0
        return len(self.completed_pages) / self.total_pages


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
            return ConversionState(**data)
        return ConversionState(file_path=file_path)

    def save(self, state: ConversionState) -> None:
        """保存转换状态。"""
        import os
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
