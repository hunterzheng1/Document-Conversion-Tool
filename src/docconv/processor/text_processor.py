"""纯文本转 Markdown。"""

from __future__ import annotations
import re


_PAGE_NUMBER_PATTERN = re.compile(r"^[-\s]*(?:第\s*\d+\s*页|Page\s*\d+|\d+)\s*[-\s]*$")
_LIST_ORDERED_PATTERN = re.compile(r"^\s*\d+\.\s+")
_LIST_UNORDERED_PATTERN = re.compile(r"^\s*[-*•]\s+")
_TITLE_PATTERN = re.compile(r"^\s*[A-Za-z一-鿿].{0,50}\s*$")


class TextProcessor:
    """将 PDF 提取的纯文本转换为基本 Markdown。"""

    def __init__(self, config: dict | None = None):
        self._config = config or {}

    def format(self, text: str, page_num: int) -> str:
        if not text.strip():
            return ""

        lines = text.split("\n")
        result = []

        for line in lines:
            # 清理页码行
            if _PAGE_NUMBER_PATTERN.match(line.strip()):
                continue

            stripped = line.strip()

            # 有序列表
            if _LIST_ORDERED_PATTERN.match(stripped):
                result.append(stripped)
            # 无序列表
            elif _LIST_UNORDERED_PATTERN.match(stripped):
                result.append(stripped)
            # 空行
            elif not stripped:
                if result and result[-1] != "":
                    result.append("")
            else:
                result.append(stripped)

        # 清理首尾空行
        while result and result[0] == "":
            result.pop(0)
        while result and result[-1] == "":
            result.pop()

        content = "\n\n".join(
            "\n".join(g)
            for g in self._group_paragraphs(result)
        )

        return f"<!-- page: {page_num} type: text_only status: completed -->\n\n{content}"

    def _group_paragraphs(self, lines: list[str]) -> list[list[str]]:
        groups: list[list[str]] = []
        current: list[str] = []

        for line in lines:
            if line == "":
                if current:
                    groups.append(current)
                    current = []
            else:
                current.append(line)

        if current:
            groups.append(current)

        return groups
