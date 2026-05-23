"""文本处理器测试。"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from docconv.processor.text_processor import TextProcessor


def test_format_empty():
    proc = TextProcessor()
    result = proc.format("", 1)
    assert result == ""


def test_format_whitespace():
    proc = TextProcessor()
    result = proc.format("   \n  \n   ", 1)
    assert result == ""


def test_format_basic_text():
    proc = TextProcessor()
    result = proc.format("Hello World\nThis is a test.", 1)
    assert "<!-- page: 1" in result
    assert "Hello World" in result


def test_format_page_number_removal():
    proc = TextProcessor()
    result = proc.format("第 1 页\n正文内容", 1)
    assert "第 1 页" not in result
    assert "正文内容" in result


def test_format_page_number_removal_english():
    proc = TextProcessor()
    result = proc.format("Page 1\n正文内容", 1)
    assert "Page 1" not in result


def test_format_paragraph_grouping():
    proc = TextProcessor()
    text = "段落1\n段落1继续\n\n段落2\n\n\n段落3"
    result = proc.format(text, 1)
    assert "段落1" in result
    assert "段落2" in result


def test_format_ordered_list():
    proc = TextProcessor()
    result = proc.format("1. 第一项\n2. 第二项", 1)
    assert "1. 第一项" in result
    assert "2. 第二项" in result


def test_format_unordered_list():
    proc = TextProcessor()
    result = proc.format("- 第一项\n* 第二项", 1)
    assert "- 第一项" in result
