"""页面分类器测试。"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from docconv.processor.page_classifier import PageClassifier, PageType


def test_classify_empty_page():
    clf = PageClassifier()
    result = clf.classify_page("", 0)
    assert result.page_type == PageType.UNKNOWN


def test_classify_text_only():
    clf = PageClassifier()
    text = "A" * 300
    result = clf.classify_page(text, 0)
    assert result.page_type == PageType.TEXT_ONLY


def test_classify_image_table():
    clf = PageClassifier()
    text = "这是一个表格，包含字段和说明。" + "A" * 100
    result = clf.classify_page(text, 1)
    assert result.page_type == PageType.IMAGE_TABLE


def test_classify_flowchart():
    clf = PageClassifier()
    text = "这是一个流程，开始到结束的判断。" + "A" * 100
    result = clf.classify_page(text, 1)
    assert result.page_type == PageType.FLOWCHART


def test_classify_mixed():
    clf = PageClassifier()
    text = "普通文本内容" * 20
    result = clf.classify_page(text, 2)
    assert result.page_type == PageType.MIXED
