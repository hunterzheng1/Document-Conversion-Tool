"""验证器测试。"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from docconv.validator.table_validator import TableValidator
from docconv.validator.mermaid_validator import MermaidValidator
from docconv.validator.content_validator import ContentValidator


def test_table_validator_valid():
    v = TableValidator()
    content = "| A | B |\n|---|---|\n| 1 | 2 |"
    valid, errors = v.validate(content)
    assert valid


def test_table_validator_invalid_separator():
    v = TableValidator()
    content = "| A | B |\n| abc |\n| 1 | 2 |"
    valid, errors = v.validate(content)
    assert not valid


def test_mermaid_validator_valid():
    v = MermaidValidator()
    content = "graph TD\nA --> B"
    valid, errors = v.validate(content)
    assert valid


def test_mermaid_validator_unbalanced_parens():
    v = MermaidValidator()
    content = "graph TD\nA(( --> B)"
    valid, errors = v.validate(content)
    assert not valid


def test_content_validator_empty():
    v = ContentValidator()
    valid, errors = v.validate_page("", 1)
    assert not valid


def test_content_validator_valid():
    v = ContentValidator()
    valid, errors = v.validate_page("<!-- page: 1 -->\n\n内容", 1)
    assert valid
