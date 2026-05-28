"""CLI 表格/列表格式化器单元测试。"""

import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))

from docconv.cli.formatters import (
    format_table,
    format_job_list,
    format_job_detail,
    format_job_output,
)


class TestFormatTable:
    """测试通用表格格式化。"""

    def test_empty_headers_returns_no_records(self):
        """空 headers 时返回"无记录"。"""
        result = format_table([], [])
        assert "无记录" in result

    def test_empty_rows(self):
        """只有 headers 无 rows 时仍输出表头。"""
        result = format_table(["Name", "Age"], [])
        assert "Name" in result
        assert "Age" in result

    def test_auto_column_width(self):
        """自动计算列宽，内容超长时不截断表头。"""
        result = format_table(
            ["Name", "City"],
            [["Alice", "New York"], ["Bob", "Shanghai"]]
        )
        lines = result.split("\n")
        # 至少应有 3 行（表头、分隔符、2条数据）
        assert len(lines) >= 3

    def test_single_row(self):
        """单条数据格式化。"""
        result = format_table(["Key", "Value"], [["Host", "localhost"]])
        assert "Host" in result
        assert "localhost" in result

    def test_multiple_rows(self):
        """多条数据格式化。"""
        rows = [
            ["A", "1"],
            ["B", "2"],
            ["C", "3"],
        ]
        result = format_table(["Label", "Num"], rows)
        assert "A" in result
        assert "B" in result
        assert "C" in result


class TestFormatJobList:
    """测试 job 列表格式化。"""

    def test_empty_list(self):
        """空列表时输出"无记录"。"""
        result = format_job_list([])
        assert "无记录" in result

    def test_single_job(self):
        """单条 job 格式化。"""
        jobs = [
            {
                "job_id": "abc-123",
                "status": "queued",
                "original_filename": "test.pdf",
                "progress": "0%",
                "created_at": "2026-01-01 10:00:00",
            }
        ]
        result = format_job_list(jobs)
        assert "abc-123" in result
        assert "queued" in result
        assert "test.pdf" in result

    def test_multiple_jobs(self):
        """多条 job 格式化。"""
        jobs = [
            {"job_id": f"id-{i}", "status": "running", "original_filename": f"file{i}.pdf",
             "progress": "50%", "created_at": "2026-01-01"}
            for i in range(5)
        ]
        result = format_job_list(jobs)
        for i in range(5):
            assert f"id-{i}" in result


class TestFormatJobDetail:
    """测试 job 详情格式化。"""

    def test_all_fields_present(self):
        """输出所有 job 字段（key: value 格式）。"""
        job = {
            "job_id": "j-001",
            "status": "running",
            "source": "web",
            "original_filename": "doc.pdf",
            "progress": "30%",
            "error_message": None,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:01:00",
        }
        result = format_job_detail(job)
        assert "j-001" in result
        assert "running" in result
        assert "web" in result
        assert "30%" in result
        assert "2026-01-01T00:00:00" in result

    def test_none_values(self):
        """None 值输出为空。"""
        job = {"job_id": "x", "status": None}
        result = format_job_detail(job)
        assert "x" in result


class TestFormatJobOutput:
    """测试 format_job_output 格式切换。"""

    def test_json_format_list(self):
        """--format json 输出 JSON 格式。"""
        jobs = [{"job_id": "1", "status": "queued"}]
        result = format_job_output(jobs, fmt="json")
        parsed = json.loads(result)
        assert parsed[0]["job_id"] == "1"

    def test_json_format_detail(self):
        """单个 job 的 JSON 输出。"""
        job = {"job_id": "1", "status": "running"}
        result = format_job_output(job, fmt="json")
        parsed = json.loads(result)
        assert parsed["job_id"] == "1"

    def test_table_format_default(self):
        """默认 table 格式。"""
        jobs = [{"job_id": "1", "status": "queued", "original_filename": "x.pdf",
                 "progress": "0%", "created_at": "now"}]
        result = format_job_output(jobs)
        assert "1" in result
        assert "queued" in result
