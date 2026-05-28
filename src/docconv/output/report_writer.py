"""转换报告生成器。"""

from __future__ import annotations

import os
from datetime import datetime

from ..core.types import ConversionResult
from ..infra.metrics import ConversionMetrics
from ..infra.service_metrics import ServiceMetricsCollector


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

    def write_report_with_metrics(
        self,
        result: ConversionResult,
        output_path: str,
        metrics: ServiceMetricsCollector | None = None,
    ) -> str:
        """写入包含服务指标摘要的转换报告。

        Args:
            result: 转换结果
            output_path: 输出路径
            metrics: 可选的服务指标收集器

        Returns:
            报告文件路径
        """
        # 先写入基本报告
        report_path = self.write_report(result, output_path)

        if metrics is None:
            return report_path

        # 追加服务指标摘要
        snap = metrics.snapshot()

        lines = ["\n", "## 服务指标摘要\n"]

        # Counter 指标
        lines.append("### 计数器\n")
        for name, value in sorted(snap.counters.items()):
            lines.append(f"- {name}: {value}")

        # Gauge 指标
        if snap.gauges:
            lines.append("\n### 仪表\n")
            for name, value in sorted(snap.gauges.items()):
                lines.append(f"- {name}: {value}")

        # Histogram 指标
        if snap.histograms:
            lines.append("\n### 直方图\n")
            for name, hist in sorted(snap.histograms.items()):
                lines.append(
                    f"- {name}: count={hist['count']}, "
                    f"avg={hist['avg']:.2f}s, "
                    f"min={hist['min']:.2f}s, "
                    f"max={hist['max']:.2f}s"
                )

        lines.append("")

        # 追加到文件
        with open(report_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return report_path
