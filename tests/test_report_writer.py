"""报告生成器测试。"""

import os
import sys
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from docconv.core.types import ConversionResult, PageContent
from docconv.infra.service_metrics import ServiceMetricsCollector
from docconv.output.report_writer import ReportWriter


class TestReportWriter:
    """测试 ReportWriter 基础功能。"""

    def test_write_report(self, tmp_path):
        output = str(tmp_path / "report.md")
        result = ConversionResult(
            file_path="test.pdf",
            total_pages=1,
            pages=[
                PageContent(
                    page_num=1,
                    page_type="text_only",
                    markdown="# Hello",
                    images_processed=0,
                    errors=[],
                ),
            ],
            errors=[],
        )

        writer = ReportWriter()
        path = writer.write_report(result, output)

        assert os.path.exists(path)
        content = open(path, encoding="utf-8").read()
        assert "PDF 转 Markdown 转换报告" in content
        assert "test.pdf" in content
        assert "1 页" in content or "| 1 |" in content

    def test_write_report_with_errors(self, tmp_path):
        output = str(tmp_path / "report_err.md")
        result = ConversionResult(
            file_path="err.pdf",
            total_pages=1,
            pages=[
                PageContent(
                    page_num=1,
                    page_type="text_only",
                    markdown="",
                    images_processed=0,
                    errors=["OCR failed"],
                ),
            ],
            errors=["Page 1 failed"],
        )

        writer = ReportWriter()
        path = writer.write_report(result, output)

        content = open(path, encoding="utf-8").read()
        assert "错误列表" in content
        assert "Page 1 failed" in content

    def test_write_report_with_metrics(self, tmp_path):
        """包含服务指标的报告。"""
        output = str(tmp_path / "report_metrics.md")
        result = ConversionResult(
            file_path="m.pdf",
            total_pages=1,
            pages=[
                PageContent(
                    page_num=1,
                    page_type="text_only",
                    markdown="test",
                    images_processed=0,
                    errors=[],
                ),
            ],
            errors=[],
        )

        metrics = ServiceMetricsCollector()
        metrics.record_job_created()
        metrics.record_job_completed("success")
        metrics.record_cache_hit()
        metrics.record_job_duration(2.5)
        metrics.set_queue_length(0)
        metrics.set_worker_count(1)

        writer = ReportWriter()
        path = writer.write_report_with_metrics(result, output, metrics=metrics)

        content = open(path, encoding="utf-8").read()
        assert "服务指标摘要" in content
        assert "计数器" in content
        assert "仪表" in content
        assert "直方图" in content
        assert "jobs_created" in content
        assert "queue_length" in content

    def test_write_report_with_metrics_none(self, tmp_path):
        """metrics 为 None 时退化为基本报告。"""
        output = str(tmp_path / "report_no_metrics.md")
        result = ConversionResult(
            file_path="x.pdf",
            total_pages=1,
            pages=[],
            errors=[],
        )

        writer = ReportWriter()
        path = writer.write_report_with_metrics(result, output, metrics=None)

        content = open(path, encoding="utf-8").read()
        assert "服务指标摘要" not in content
