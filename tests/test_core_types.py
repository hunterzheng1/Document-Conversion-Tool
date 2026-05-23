"""核心类型测试。"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from docconv.core.types import PageContent, ConversionResult, ConversionConfig


def test_page_content():
    page = PageContent(page_num=1, page_type="text_only", markdown="# Test")
    assert page.page_num == 1
    assert page.page_type == "text_only"


def test_conversion_result():
    result = ConversionResult(
        file_path="/test.pdf",
        total_pages=3,
        pages=[
            PageContent(page_num=1, page_type="text_only", markdown="p1"),
            PageContent(page_num=2, page_type="text_only", markdown="p2"),
            PageContent(page_num=3, page_type="text_only", markdown="p3"),
        ],
    )
    assert result.total_pages == 3
    assert result.success_pages == 3
    assert result.failed_pages == 0
    assert "p1" in result.output_markdown


def test_conversion_result_with_errors():
    result = ConversionResult(
        file_path="/test.pdf",
        total_pages=2,
        pages=[
            PageContent(page_num=1, page_type="text_only", markdown="p1"),
            PageContent(page_num=2, page_type="text_only", markdown="", errors=["error"]),
        ],
    )
    assert result.success_pages == 1
    assert result.failed_pages == 1


def test_conversion_config():
    cfg = ConversionConfig(
        input_path="/test.pdf",
        output_path="/test.md",
        resume=True,
        parallel=4,
    )
    assert cfg.input_path == "/test.pdf"
    assert cfg.resume is True
