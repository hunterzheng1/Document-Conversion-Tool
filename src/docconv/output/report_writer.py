"""转换报告生成器。"""

from __future__ import annotations

import os
from datetime import datetime

from ..core.types import ConversionResult
from ..infra.metrics import ConversionMetrics


class ReportWriter:
    """生成转换摘要报告。"""

    def write_report(self, result: ConversionResult, output_path: str) -> str:
        """写入转换报告。

        Returns:
            报告文件路径
        """
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        lines = [
            "# PDF 转 Markdown 转换报告\n",
            f"**源文件**: {result.file_path}",
            f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**总页数**: {result.total_pages}",
            f"**成功页数**: {result.success_pages}",
            f"**失败页数**: {result.failed_pages}",
            f"**耗时**: {result.duration_seconds:.1f}s",
            "",
        ]

        if result.errors:
            lines.append("## 错误列表\n")
            for err in result.errors:
                lines.append(f"- {err}")
            lines.append("")

        lines.append("## 页面摘要\n")
        lines.append("| 页码 | 类型 | 图片数 | 状态 |")
        lines.append("|------|------|--------|------|")
        for page in result.pages:
            status = "失败" if page.errors else "成功"
            lines.append(
                f"| {page.page_num} | {page.page_type} | {page.images_processed} | {status} |"
            )

        tmp_path = output_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        os.replace(tmp_path, output_path)
        return output_path
