"""状态管理器测试。"""

import sys
import os
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from docconv.infra.state_manager import StateManager, ConversionState


def test_load_empty_state():
    with tempfile.TemporaryDirectory() as tmp:
        mgr = StateManager({"state_dir": tmp})
        state = mgr.load("/path/to/file.pdf")
        assert state.file_path == "/path/to/file.pdf"
        assert state.status == "pending"
        assert state.progress == 0.0


def test_save_and_load():
    with tempfile.TemporaryDirectory() as tmp:
        mgr = StateManager({"state_dir": tmp})
        state = ConversionState(
            file_path="/test.pdf",
            total_pages=5,
            completed_pages=[0, 1, 2],
            status="paused",
        )
        mgr.save(state)

        loaded = mgr.load("/test.pdf")
        assert loaded.total_pages == 5
        assert len(loaded.completed_pages) == 3
        assert loaded.status == "paused"


def test_delete_state():
    with tempfile.TemporaryDirectory() as tmp:
        mgr = StateManager({"state_dir": tmp})
        state = ConversionState(file_path="/delete.pdf", total_pages=3)
        mgr.save(state)
        mgr.delete("/delete.pdf")
        loaded = mgr.load("/delete.pdf")
        assert loaded.total_pages == 0
