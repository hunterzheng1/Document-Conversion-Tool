"""StateManager 单元测试：双模式（CLI/服务）、load/save/delete、原子写入、向后兼容。"""

import json
import os
import time
import tempfile
from pathlib import Path

import pytest

from docconv.infra.state_manager import (
    StateManager, ConversionState, PageInfo, PageStatus, StateConfig,
)
from docconv.core.exceptions import StateWriteError


# ===================================================================
# StateConfig 测试
# ===================================================================

class TestStateConfig:
    def test_default_values(self):
        cfg = StateConfig()
        assert cfg.state_dir == ".docconv_state"
        assert cfg.enabled is True
        assert cfg.atomic_write is True
        assert cfg.recover_processing is True
        assert cfg.state_lock_timeout_ms == 5000
        assert cfg.atomic_write_retry_interval_ms == 100
        assert cfg.recovery_scan_timeout_ms == 30000

    def test_from_dict(self):
        cfg = StateConfig.from_dict({
            "state_dir": "/custom/path",
            "enabled": False,
        })
        assert cfg.state_dir == "/custom/path"
        assert cfg.enabled is False
        # 其他字段保持默认值
        assert cfg.atomic_write is True

    def test_from_dict_ignores_unknown_keys(self):
        cfg = StateConfig.from_dict({
            "state_dir": "/path",
            "unknown_key": "ignored",
        })
        assert cfg.state_dir == "/path"

    def test_timeout_conversions(self):
        cfg = StateConfig(state_lock_timeout_ms=10000)
        assert cfg.state_lock_timeout_sec == 10.0
        assert cfg.atomic_write_retry_interval_sec == 0.1
        assert cfg.recovery_scan_timeout_sec == 30.0


# ===================================================================
# ConversionState 测试
# ===================================================================

class TestConversionState:
    def test_new_fields_defaults(self):
        state = ConversionState()
        assert state.job_id is None
        assert state.schema_version == 2
        assert state.workspace is None

    def test_completed_count(self):
        state = ConversionState(completed_pages=[0, 1, 2, 5])
        assert state.completed_count == 4

    def test_failed_count(self):
        state = ConversionState(failed_pages={3: "error1", 7: "error2"})
        assert state.failed_count == 2

    def test_asdict_includes_new_fields(self):
        from dataclasses import asdict as dc_asdict
        state = ConversionState(
            job_id="job_123",
            schema_version=2,
            workspace="/workspace",
            file_path="/test.pdf",
        )
        d = dc_asdict(state)
        assert d["job_id"] == "job_123"
        assert d["schema_version"] == 2
        assert d["workspace"] == "/workspace"

    def test_backward_compat_old_json(self):
        """从旧 state.json（缺少 job_id 等字段）反序列化时不抛异常。"""
        old_data = {
            "file_path": "/old.pdf",
            "total_pages": 5,
            "completed_pages": [0, 1],
            "failed_pages": {},
            "status": "pending",
            "pages": {},
            "started_at": 0.0,
            "updated_at": 0.0,
            "errors": [],
            # 缺少 job_id, schema_version, workspace
        }
        state = ConversionState(**old_data)
        assert state.file_path == "/old.pdf"
        assert state.job_id is None
        assert state.schema_version == 2
        assert state.workspace is None


# ===================================================================
# StateManager CLI 模式测试
# ===================================================================

class TestStateManagerCLI:
    def test_load_empty_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = StateManager({"state_dir": tmp})
            state = mgr.load("/path/to/file.pdf")
            assert state.file_path == "/path/to/file.pdf"
            assert state.status == "pending"
            assert state.progress == 0.0

    def test_save_and_load(self):
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

    def test_delete_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = StateManager({"state_dir": tmp})
            state = ConversionState(file_path="/delete.pdf", total_pages=3)
            mgr.save(state)
            mgr.delete("/delete.pdf")
            loaded = mgr.load("/delete.pdf")
            assert loaded.total_pages == 0

    def test_list_states(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = StateManager({"state_dir": tmp})
            # 直接写 JSON 文件到 state_dir（绕过 save 的路径派生）
            import json
            for name, pages in [("a.pdf", 1), ("b.pdf", 2)]:
                state_file = Path(tmp) / f"{name.replace(os.sep, '_').replace(':', '')}.json"
                with open(state_file, "w") as f:
                    json.dump({
                        "file_path": f"/{name}",
                        "total_pages": pages,
                        "completed_pages": [],
                        "failed_pages": {},
                        "status": "pending",
                        "pages": {},
                        "started_at": 0.0,
                        "updated_at": 0.0,
                        "errors": [],
                    }, f)
            states = mgr.list_states()
            assert len(states) == 2

    def test_updated_at_updated_on_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = StateManager({"state_dir": tmp})
            state = ConversionState(file_path="/t.pdf", updated_at=0.0)
            mgr.save(state)
            loaded = mgr.load("/t.pdf")
            assert loaded.updated_at > 0.0

    def test_json_file_is_actual_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = StateManager({"state_dir": tmp})
            state = ConversionState(file_path="/check.pdf", total_pages=3)
            mgr.save(state)
            state_file = mgr._state_file("/check.pdf")
            assert state_file.exists()
            with open(state_file) as f:
                data = json.load(f)
            assert data["total_pages"] == 3


# ===================================================================
# StateManager 原子写入测试
# ===================================================================

class TestAtomicWrite:
    def test_atomic_write_produces_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = StateManager({"state_dir": tmp})
            state = ConversionState(
                file_path="/atomic.pdf",
                total_pages=10,
                completed_pages=list(range(10)),
                status="completed",
            )
            mgr.save(state)
            state_file = mgr._state_file("/atomic.pdf")
            # 不应有 .tmp 残留
            assert not state_file.with_suffix(".tmp").exists()
            with open(state_file, encoding="utf-8") as f:
                data = json.load(f)
            assert data["status"] == "completed"
            assert len(data["completed_pages"]) == 10

    def test_write_failure_raises_state_write_error(self, monkeypatch):
        """写入失败重试后抛出 StateWriteError。"""
        with tempfile.TemporaryDirectory() as tmp:
            mgr = StateManager({"state_dir": tmp})
            state = ConversionState(file_path="/fail.pdf")

            # 模拟 open 永远失败
            def failing_open(*args, **kwargs):
                raise OSError("disk full")

            monkeypatch.setattr("builtins.open", failing_open)
            with pytest.raises(StateWriteError) as exc_info:
                mgr.save(state)
            assert exc_info.value.error_code == "ST5001"


# ===================================================================
# 向后兼容旧 state.json
# ===================================================================

class TestBackwardCompat:
    def test_load_old_json_without_new_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            # 先 save 一个旧格式状态，然后手动修改 JSON 去掉新字段
            mgr = StateManager({"state_dir": tmp})
            old_data = {
                "file_path": "/old.pdf",
                "total_pages": 5,
                "completed_pages": [0, 1],
                "failed_pages": {},
                "status": "paused",
                "pages": {},
                "started_at": 0.0,
                "updated_at": 0.0,
                "errors": [],
            }
            # 直接写入状态文件（使用 mgr._state_file 生成的路径）
            state_file = mgr._state_file("/old.pdf")
            with open(state_file, "w") as f:
                json.dump(old_data, f)

            state = mgr.load("/old.pdf")
            assert state.total_pages == 5
            assert state.job_id is None
            assert state.schema_version == 2

    def test_load_old_json_with_new_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = StateManager({"state_dir": tmp})
            data = {
                "file_path": "/new.pdf",
                "total_pages": 5,
                "completed_pages": [0, 1],
                "failed_pages": {},
                "status": "running",
                "pages": {},
                "started_at": 0.0,
                "updated_at": 0.0,
                "errors": [],
                "job_id": "job_abc",
                "schema_version": 2,
                "workspace": "/workspace/job_abc",
            }
            state_file = mgr._state_file("/new.pdf")
            with open(state_file, "w") as f:
                json.dump(data, f)

            state = mgr.load("/new.pdf")
            assert state.job_id == "job_abc"
            assert state.schema_version == 2
            assert state.workspace == "/workspace/job_abc"


# ===================================================================
# 清理与归档测试
# ===================================================================

class TestCleanupArchive:
    def test_cleanup_completed_old_states(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = StateManager({"state_dir": tmp})
            # 直接写入 JSON 文件（绕过 save 的 updated_at 覆盖）
            state_file = Path(tmp) / "old_pdf.json"
            old_data = {
                "file_path": "/old.pdf",
                "total_pages": 3,
                "completed_pages": [0, 1, 2],
                "failed_pages": {},
                "status": "completed",
                "pages": {},
                "started_at": time.time() - (60 * 86400),
                "updated_at": time.time() - (60 * 86400),
                "errors": [],
            }
            with open(state_file, "w") as f:
                json.dump(old_data, f)

            count = mgr.cleanup_completed(older_than_days=30)
            assert count == 1
            assert not state_file.exists()

    def test_cleanup_does_not_remove_recent_states(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = StateManager({"state_dir": tmp})
            state = ConversionState(
                file_path="/recent.pdf",
                status="completed",
            )
            mgr.save(state)
            count = mgr.cleanup_completed(older_than_days=30)
            assert count == 0

    def test_archive_state_moves_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = StateManager({"state_dir": tmp})
            state = ConversionState(file_path="/archive.pdf", total_pages=3)
            mgr.save(state)
            state_file = mgr._state_file("/archive.pdf")

            archive_dir = Path(tmp) / "archive"
            result = mgr.archive_state("/archive.pdf", archive_dir)
            assert result is True
            # 验证原状态文件已被移走
            assert not state_file.exists()
            # 验证归档目录中有 state.json
            archived = list((archive_dir).rglob("state.json"))
            assert len(archived) == 1

    def test_get_state_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = StateManager({"state_dir": tmp})
            state = ConversionState(file_path="/size.pdf", total_pages=3)
            mgr.save(state)
            size = mgr.get_state_size("/size.pdf")
            assert size > 0
