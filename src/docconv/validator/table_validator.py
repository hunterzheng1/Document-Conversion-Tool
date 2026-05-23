"""表格验证器：验证 Markdown 表格格式。"""

from __future__ import annotations

import re


class TableValidator:
    """验证 Markdown 表格格式是否正确。"""

    def validate(self, content: str) -> tuple[bool, list[str]]:
        """验证表格内容。

        Returns:
            (is_valid, errors) 元组
        """
        errors = []
        lines = content.split("\n")

        in_table = False
        row_count = 0
        header_cols = 0

        for i, line in enumerate(lines):
            stripped = line.strip()

            if "|" in stripped:
                cells = [c.strip() for c in stripped.split("|")]
                cells = [c for c in cells if c]

                if not in_table:
                    in_table = True
                    header_cols = len(cells)
                    row_count = 0

                row_count += 1

                # 检查分隔行
                if row_count == 2:
                    if not all(re.match(r"^[-:]+$", c) for c in cells):
                        errors.append(f"第 {i + 1} 行：表格分隔行格式不正确")

                # 检查列数一致性
                if row_count > 2 and len(cells) != header_cols:
                    errors.append(f"第 {i + 1} 行：列数不一致（期望 {header_cols}，实际 {len(cells)}）")

            elif in_table:
                in_table = False
                if row_count < 2:
                    errors.append(f"第 {i} 行：表格行数不足")

        return len(errors) == 0, errors
