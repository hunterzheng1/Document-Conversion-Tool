"""SQLiteStateRepository 单元测试：CRUD、并发安全、原子操作、迁移框架。"""

import json
import sqlite3
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from docconv.service.state_repo import SQLiteStateRepository
from docconv.core.exceptions import StateFormatError


class TestSQLiteStateRepositoryCRUD:
    """基础 CRUD 测试。"""

    def test_upsert_and_get_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteStateRepository(data_dir=tmp)
            repo.upsert_page(
                job_id="job_1",
                page_num=1,
                status="completed",
                markdown="# Page 1",
                errors=[],
            )
            pages = repo.get_pages("job_1")
            assert len(pages) == 1
            assert pages[0]["page_num"] == 1
            assert pages[0]["page_status"] == "completed"
            assert pages[0]["markdown"] == "# Page 1"

    def test_upsert_updates_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteStateRepository(data_dir=tmp)
            repo.upsert_page("job_1", 1, "processing", "", [])
            repo.upsert_page("job_1", 1, "completed", "# Done", [])
            pages = repo.get_pages("job_1")
            assert len(pages) == 1
            assert pages[0]["page_status"] == "completed"
            assert pages[0]["markdown"] == "# Done"

    def test_load_nonexistent_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteStateRepository(data_dir=tmp)
            page = repo.get_page("nonexistent_job", 1)
            assert page is None

    def test_delete_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteStateRepository(data_dir=tmp)
            repo.upsert_page("job_1", 1, "completed", "", [])
            repo.upsert_page("job_1", 2, "completed", "", [])
            repo.upsert_page("job_2", 1, "pending", "", [])
            deleted = repo.delete_job("job_1")
            assert deleted == 2
            assert len(repo.get_pages("job_1")) == 0
            assert len(repo.get_pages("job_2")) == 1

    def test_delete_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteStateRepository(data_dir=tmp)
            repo.upsert_page("job_1", 1, "completed", "", [])
            repo.upsert_page("job_1", 2, "completed", "", [])
            assert repo.delete_page("job_1", 1) is True
            assert repo.delete_page("job_1", 99) is False
            pages = repo.get_pages("job_1")
            assert len(pages) == 1

    def test_list_by_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteStateRepository(data_dir=tmp)
            repo.upsert_page("job_1", 1, "completed", "", [])
            repo.upsert_page("job_1", 2, "failed", "", ["error"])
            repo.upsert_page("job_1", 3, "completed", "", [])
            completed = repo.get_pages_by_status("job_1", "completed")
            assert len(completed) == 2

    def test_progress_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteStateRepository(data_dir=tmp)
            repo.upsert_page("job_1", 1, "completed", "", [])
            repo.upsert_page("job_1", 2, "completed", "", [])
            repo.upsert_page("job_1", 3, "failed", "", ["err"])
            repo.upsert_page("job_1", 4, "processing", "", [])
            repo.upsert_page("job_1", 5, "pending", "", [])
            summary = repo.get_progress_summary("job_1")
            assert summary["total"] == 5
            assert summary["completed"] == 2
            assert summary["failed"] == 1
            assert summary["processing"] == 1
            assert summary["pending"] == 1
            assert abs(summary["progress"] - 0.4) < 0.001

    def test_progress_summary_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteStateRepository(data_dir=tmp)
            summary = repo.get_progress_summary("empty_job")
            assert summary["total"] == 0
            assert summary["progress"] == 0.0

    def test_errors_json_serialized(self):
        """errors 字段应序列化为 JSON 数组并正确反序列化。"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteStateRepository(data_dir=tmp)
            repo.upsert_page(
                "job_1", 1, "failed", "",
                ["timeout", "retry exhausted"],
            )
            page = repo.get_page("job_1", 1)
            assert isinstance(page["errors"], list)
            assert page["errors"] == ["timeout", "retry exhausted"]


class TestSQLiteConcurrency:
    """并发写入安全测试。"""

    def test_concurrent_upsert_same_job(self):
        """多线程并发更新同一 job 不应导致数据损坏。"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteStateRepository(data_dir=tmp)
            job_id = "concurrent_job"

            def upsert_page(page_num: int):
                repo.upsert_page(
                    job_id=job_id,
                    page_num=page_num,
                    status="completed",
                    markdown=f"# Page {page_num}",
                    errors=[],
                )

            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = [
                    pool.submit(upsert_page, i)
                    for i in range(1, 21)
                ]
                for f in as_completed(futures):
                    f.result()  # 不应抛异常

            pages = repo.get_pages(job_id)
            assert len(pages) == 20

    def test_save_or_update(self):
        """save_or_update 应等同于 upsert_page。"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteStateRepository(data_dir=tmp)
            repo.save_or_update(
                job_id="job_1",
                page_num=1,
                status="completed",
                markdown="# Test",
            )
            page = repo.get_page("job_1", 1)
            assert page["page_status"] == "completed"

    def test_atomic_claim_progress(self):
        """atomic_claim_progress 应返回正确的进度摘要。"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteStateRepository(data_dir=tmp)
            repo.upsert_page("job_1", 1, "completed", "", [])
            repo.upsert_page("job_1", 2, "completed", "", [])
            repo.upsert_page("job_1", 3, "failed", "", ["err"])
            summary = repo.atomic_claim_progress("job_1")
            assert summary["total"] == 3
            assert summary["completed"] == 2
            assert summary["failed"] == 1


class TestMigrationFramework:
    """数据库迁移框架测试。"""

    def test_init_creates_migration_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteStateRepository(data_dir=tmp)
            version = repo.get_schema_version()
            assert version >= 1

    def test_migrate_up_to_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteStateRepository(data_dir=tmp)
            result = repo.migrate()
            assert result["status"] == "up-to-date"
            assert result["applied_migrations"] == []

    def test_migrate_downward_incompatible_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteStateRepository(data_dir=tmp)
            with pytest.raises(StateFormatError) as exc_info:
                repo.migrate(to_version=0)
            assert exc_info.value.error_code == "ST1001"
            assert "向下不兼容" in str(exc_info.value)

    def test_migration_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteStateRepository(data_dir=tmp)
            # 多次调用不应报错
            r1 = repo.migrate()
            r2 = repo.migrate()
            assert r1["status"] == "up-to-date"
            assert r2["status"] == "up-to-date"

    def test_schema_migrations_table_exists(self):
        """schema_migrations 表应存在并包含正确数据。"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteStateRepository(data_dir=tmp)
            conn = sqlite3.connect(str(repo._db_path))
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
            )
            assert cursor.fetchone() is not None
            conn.close()

    def test_migration_undefined_version_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteStateRepository(data_dir=tmp)
            with pytest.raises(StateFormatError) as exc_info:
                repo.migrate(to_version=999)
            assert "未定义迁移版本" in str(exc_info.value)
