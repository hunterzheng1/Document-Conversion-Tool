"""PageArtifactWriter 单元测试：原子写入、读取、存在检查、路径安全。"""

import json
import os
import tempfile

import pytest

from docconv.infra.artifact_writer import PageArtifactWriter
from docconv.core.exceptions import ArtifactWriteError


class TestPageArtifactWriter:
    """基础 write/read/exists 测试。"""

    def test_write_and_read_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = PageArtifactWriter(tmp)
            md_path, meta_path = writer.write_page(
                job_id="job_1",
                page_num=1,
                content="# Hello World",
                meta={"type": "text"},
            )
            assert os.path.exists(md_path)
            assert os.path.exists(meta_path)

            content = writer.read_page("job_1", 1)
            assert content == "# Hello World"

    def test_write_page_creates_meta_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = PageArtifactWriter(tmp)
            meta = {"page_type": "table", "confidence": 0.95}
            writer.write_page(
                job_id="job_1",
                page_num=2,
                content="# Table",
                meta=meta,
            )
            read_meta = writer.read_meta("job_1", 2)
            assert read_meta is not None
            assert read_meta["page_type"] == "table"
            assert read_meta["confidence"] == 0.95

    def test_read_nonexistent_page_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = PageArtifactWriter(tmp)
            assert writer.read_page("job_1", 99) is None

    def test_read_nonexistent_meta_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = PageArtifactWriter(tmp)
            assert writer.read_meta("job_1", 99) is None

    def test_page_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = PageArtifactWriter(tmp)
            assert writer.page_exists("job_1", 1) is False
            writer.write_page("job_1", 1, "content")
            assert writer.page_exists("job_1", 1) is True

    def test_delete_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = PageArtifactWriter(tmp)
            writer.write_page("job_1", 1, "content", {"key": "val"})
            assert writer.delete_page("job_1", 1) is True
            assert writer.page_exists("job_1", 1) is False

    def test_list_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = PageArtifactWriter(tmp)
            writer.write_page("job_1", 3, "page 3")
            writer.write_page("job_1", 1, "page 1")
            writer.write_page("job_1", 2, "page 2")
            pages = writer.list_pages("job_1")
            assert pages == [1, 2, 3]

    def test_write_page_returns_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = PageArtifactWriter(tmp)
            md_path, meta_path = writer.write_page("job_1", 1, "content")
            assert md_path.endswith("page_0001.md")
            assert meta_path.endswith("page_0001.meta.json")


class TestAtomicWrite:
    """原子写入测试。"""

    def test_no_tmp_files_after_write(self):
        """写入完成后不应残留 .tmp 文件。"""
        with tempfile.TemporaryDirectory() as tmp:
            writer = PageArtifactWriter(tmp)
            writer.write_page("job_1", 1, "content")
            pages_dir = writer._pages_dir
            tmp_files = list(pages_dir.glob("*.tmp"))
            assert len(tmp_files) == 0

    def test_write_failure_cleans_up_tmp(self):
        """写入失败时应清理残留临时文件。"""
        with tempfile.TemporaryDirectory() as tmp:
            writer = PageArtifactWriter(tmp)
            # 通过覆盖 open 来模拟写入失败
            import builtins
            original_open = builtins.open
            call_count = [0]

            def failing_open(path, mode="r", *args, **kwargs):
                call_count[0] += 1
                if call_count[0] == 1:
                    # 第一次调用（写 .tmp）正常
                    return original_open(path, mode, *args, **kwargs)
                # 后续调用失败
                raise OSError("disk full")

            try:
                builtins.open = failing_open
                with pytest.raises(ArtifactWriteError):
                    writer.write_page("job_1", 1, "content")
            finally:
                builtins.open = original_open

            # 检查没有残留 .tmp 文件
            tmp_files = list(writer._pages_dir.glob("*.tmp"))
            assert len(tmp_files) == 0


class TestPathSafety:
    """路径安全测试。"""

    def test_invalid_page_num_raises(self):
        """page_num 必须为正整数。"""
        with tempfile.TemporaryDirectory() as tmp:
            writer = PageArtifactWriter(tmp)
            with pytest.raises(ValueError):
                writer.write_page("job_1", 0, "content")

    def test_negative_page_num_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = PageArtifactWriter(tmp)
            with pytest.raises(ValueError):
                writer.write_page("job_1", -1, "content")

    def test_float_page_num_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = PageArtifactWriter(tmp)
            with pytest.raises(ValueError):
                writer.write_page("job_1", 1.5, "content")

    def test_string_page_num_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = PageArtifactWriter(tmp)
            with pytest.raises(ValueError):
                writer.write_page("job_1", "1", "content")

    def test_no_path_traversal_in_filename(self):
        """文件名不应包含路径穿越字符。"""
        with tempfile.TemporaryDirectory() as tmp:
            writer = PageArtifactWriter(tmp)
            writer.write_page("job_1", 1, "content")
            # 文件应在 pages/ 目录下，不应有子目录
            md_path = writer._page_path(1)
            assert md_path.parent == writer._pages_dir


class TestArtifactWriteError:
    """ArtifactWriteError 异常测试。"""

    def test_write_error_raises_artifact_write_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = PageArtifactWriter(tmp)
            # 将 workspace 设置为一个不可写的路径
            import builtins
            original_open = builtins.open

            def failing_open(path, mode="r", *args, **kwargs):
                raise PermissionError("access denied")

            try:
                builtins.open = failing_open
                with pytest.raises(ArtifactWriteError) as exc_info:
                    writer.write_page("job_1", 1, "content")
                assert exc_info.value.error_code == "ST5002"
            finally:
                builtins.open = original_open
