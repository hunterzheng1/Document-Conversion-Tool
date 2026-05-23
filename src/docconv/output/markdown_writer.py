"""Markdown 输出写入器。"""

from __future__ import annotations

import os
from pathlib import Path

from ..core.types import ConversionResult


class MarkdownWriter:
    """将转换结果写入 Markdown 文件。"""

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self._output_dir = cfg.get("output_dir", "output")

    def write(self, result: ConversionResult, output_path: str | None = None) -> str:
        """写入 Markdown 文件。

        Args:
            result: 转换结果
            output_path: 输出路径（可选，默认从文件名推导）

        Returns:
            输出文件路径
        """
        if output_path is None:
            base = Path(result.file_path).stem
            output_path = os.path.join(self._output_dir, f"{base}.md")

        # 确保输出目录存在
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        # 原子写入
        tmp_path = output_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(result.output_markdown)

        os.replace(tmp_path, output_path)
        return output_path
