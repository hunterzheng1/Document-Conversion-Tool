"""Mermaid 验证器：验证 Mermaid 语法基本格式。"""

from __future__ import annotations


class MermaidValidator:
    """验证 Mermaid 图表语法。"""

    def validate(self, content: str) -> tuple[bool, list[str]]:
        """验证 Mermaid 代码。

        Returns:
            (is_valid, errors) 元组
        """
        errors = []
        lines = content.split("\n")

        # 检查是否以 graph/subgraph 开头
        found_graph = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("graph ") or stripped.startswith("subgraph "):
                found_graph = True
                break

        if not found_graph and content.strip():
            errors.append("Mermaid 代码应以 graph 或 subgraph 开头")

        # 检查括号匹配
        open_parens = content.count("(")
        close_parens = content.count(")")
        if open_parens != close_parens:
            errors.append(f"括号不匹配：({open_parens} vs ){close_parens}")

        return len(errors) == 0, errors
