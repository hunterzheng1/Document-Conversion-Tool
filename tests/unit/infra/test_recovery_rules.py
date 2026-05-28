"""恢复规则单元测试：覆盖 spec.md 全部恢复场景。

场景：
1. processing 页面降级为 pending
2. completed 但 artifact 丢失的页面降级为 pending
3. completed 且 artifact 存在的页面跳过
4. failed 页面默认重试
"""

import json
import os
import tempfile
from pathlib import Path

import pytest

from docconv.infra.state_manager import (
    StateManager, ConversionState, PageStatus,
)


def _make_state_with_pages(total=3) -> ConversionState:
    """创建一个带有页面状态的 ConversionState。"""
    state = ConversionState(
        file_path="/test.pdf",
        total_pages=total,
    )
    for i in range(total):
        state.pages[i] = {
            "status": PageStatus.PENDING,
            "artifact": None,
            "meta": None,
            "attempts": 0,
            "error_type": None,
        }
    return state


class TestRecoveryProcessing:
    """processing 页面降级为 pending。"""

    def test_processing_downgraded_to_pending(self):
        state = _make_state_with_pages(3)
        state.pages[1]["status"] = PageStatus.PROCESSING

        with tempfile.TemporaryDirectory() as tmp:
            mgr = StateManager({"state_dir": tmp})
            resume = mgr.get_resume_pages(state)

            assert resume[0] is True  # pending -> process
            assert resume[1] is True  # processing -> downgraded to pending
            assert resume[2] is True  # pending -> process
            assert state.pages[1]["status"] == PageStatus.PENDING


class TestRecoveryCompleted:
    """completed 页面根据 artifact 存在性决定行为。"""

    def test_completed_with_existing_artifact_skipped(self):
        """artifact 存在的 completed 页面应跳过。"""
        with tempfile.TemporaryDirectory() as tmp:
            artifact_path = os.path.join(tmp, "page_0001.md")
            with open(artifact_path, "w") as f:
                f.write("# Page 1")

            state = _make_state_with_pages(2)
            state.pages[0]["status"] = PageStatus.COMPLETED
            state.pages[0]["artifact"] = artifact_path
            state.pages[1]["status"] = PageStatus.PENDING

            mgr = StateManager({"state_dir": tmp})
            resume = mgr.get_resume_pages(state)

            assert resume[0] is False  # completed with artifact -> skip
            assert resume[1] is True   # pending -> process

    def test_completed_with_missing_artifact_downgraded(self):
        """artifact 丢失的 completed 页面降级为 pending。"""
        with tempfile.TemporaryDirectory() as tmp:
            state = _make_state_with_pages(2)
            state.pages[0]["status"] = PageStatus.COMPLETED
            state.pages[0]["artifact"] = "/nonexistent/page_0001.md"
            state.pages[1]["status"] = PageStatus.PENDING

            mgr = StateManager({"state_dir": tmp})
            resume = mgr.get_resume_pages(state)

            assert resume[0] is True  # missing artifact -> pending
            assert state.pages[0]["status"] == PageStatus.PENDING

    def test_missing_artifact_records_warning_in_errors(self):
        """artifact 丢失时在 state.errors 中记录 warning。"""
        with tempfile.TemporaryDirectory() as tmp:
            state = _make_state_with_pages(1)
            state.pages[0]["status"] = PageStatus.COMPLETED
            state.pages[0]["artifact"] = "/nonexistent/page_0001.md"

            mgr = StateManager({"state_dir": tmp})
            mgr.get_resume_pages(state)

            assert len(state.errors) > 0
            assert "warning" in state.errors[0].lower()
            assert "missing" in state.errors[0].lower()


class TestRecoveryFailed:
    """failed 页面默认重试。"""

    def test_failed_page_retried(self):
        state = _make_state_with_pages(2)
        state.pages[0]["status"] = PageStatus.FAILED
        state.pages[0]["error_type"] = "timeout"
        state.pages[1]["status"] = PageStatus.PENDING

        with tempfile.TemporaryDirectory() as tmp:
            mgr = StateManager({"state_dir": tmp})
            resume = mgr.get_resume_pages(state)

            assert resume[0] is True  # failed -> retry
            assert resume[1] is True  # pending -> process


class TestRecoveryMixed:
    """混合场景测试。"""

    def test_mixed_states(self):
        """同时包含 processing, completed, failed, pending 页面。"""
        with tempfile.TemporaryDirectory() as tmp:
            artifact_path = os.path.join(tmp, "page_0002.md")
            with open(artifact_path, "w") as f:
                f.write("# Page 2")

            state = _make_state_with_pages(5)
            state.pages[0]["status"] = PageStatus.PROCESSING
            state.pages[1]["status"] = PageStatus.COMPLETED
            state.pages[1]["artifact"] = artifact_path
            state.pages[2]["status"] = PageStatus.COMPLETED
            state.pages[2]["artifact"] = "/nonexistent.md"  # missing
            state.pages[3]["status"] = PageStatus.FAILED
            state.pages[4]["status"] = PageStatus.PENDING

            mgr = StateManager({"state_dir": tmp})
            resume = mgr.get_resume_pages(state)

            assert resume[0] is True   # processing -> pending -> retry
            assert resume[1] is False  # completed + artifact exists -> skip
            assert resume[2] is True   # completed + missing artifact -> pending
            assert resume[3] is True   # failed -> retry
            assert resume[4] is True   # pending -> process


class TestRecoveryLoad:
    """从 JSON 文件加载时自动应用恢复规则。"""

    def test_load_applies_recovery(self):
        """从 JSON 加载时，processing 页面应自动降级为 pending。"""
        with tempfile.TemporaryDirectory() as tmp:
            mgr = StateManager({"state_dir": tmp})
            # 使用 mgr._state_file 生成的路径
            state_file = mgr._state_file("/test.pdf")
            data = {
                "file_path": "/test.pdf",
                "total_pages": 2,
                "pages": {
                    "0": {"status": "processing", "artifact": None, "meta": None, "attempts": 1, "error_type": None},
                    "1": {"status": "pending", "artifact": None, "meta": None, "attempts": 0, "error_type": None},
                },
                "completed_pages": [],
                "failed_pages": {},
                "status": "running",
                "started_at": 0.0,
                "updated_at": 0.0,
                "errors": [],
            }
            with open(state_file, "w") as f:
                json.dump(data, f)

            state = mgr.load("/test.pdf")

            # 验证 recovery rules 已执行：processing 降级为 pending
            processing_downgraded = False
            for key, page_data in state.pages.items():
                if key == "0" and page_data["status"] == PageStatus.PENDING:
                    processing_downgraded = True
            assert processing_downgraded, "processing 页面应降级为 pending"
