"""PDF 解析器测试。"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from docconv.parser.errors import (
    FileNotFoundError,
    PDFPasswordError,
    PDFParseError,
    PageRenderError,
)


def test_file_not_found_error():
    err = FileNotFoundError("测试文件不存在")
    assert err.message == "测试文件不存在"
    assert str(err) == "测试文件不存在"


def test_pdf_password_error():
    err = PDFPasswordError("密码错误")
    assert err.message == "密码错误"


def test_pdf_parse_error():
    err = PDFParseError("解析失败")
    assert err.message == "解析失败"


def test_page_render_error():
    err = PageRenderError("渲染失败")
    assert err.message == "渲染失败"


def test_parser_raises_on_missing_file():
    from docconv.parser.pdf_parser import PDFParser
    try:
        PDFParser("/nonexistent/file.pdf")
        assert False, "应抛出 FileNotFoundError"
    except FileNotFoundError:
        pass
