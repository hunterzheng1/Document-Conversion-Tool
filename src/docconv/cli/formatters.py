"""CLI 输出格式化工具：表格/列表格式化。"""

from __future__ import annotations

import json


def format_table(headers: list[str], rows: list[list[str]]) -> str:
    """通用表格格式化，自动计算列宽。

    Args:
        headers: 表头列表
        rows: 数据行列表，每行是与 headers 等长的字符串列表

    Returns:
        对齐的表格文本
    """
    if not headers:
        return "无记录"

    # 计算每列最大宽度
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], len(str(cell)))

    # 构建格式字符串
    fmt = "  ".join(f"{{:<{w}}}" for w in col_widths)

    lines = [fmt.format(*headers)]
    separator = "  ".join("-" * w for w in col_widths)
    lines.append(separator)

    for row in rows:
        padded = [str(row[i]) if i < len(row) else "" for i in range(len(headers))]
        lines.append(fmt.format(*padded))

    return "\n".join(lines)


def format_job_list(jobs: list[dict]) -> str:
    """以表格形式输出 job 列表。

    列: job_id, status, filename, progress, created_at
    """
    if not jobs:
        return "无记录"

    headers = ["JOB ID", "STATUS", "FILENAME", "PROGRESS", "CREATED AT"]
    rows = []
    for j in jobs:
        rows.append([
            str(j.get("job_id", ""))[:35],
            str(j.get("status", ""))[:12],
            str(j.get("original_filename", ""))[:25],
            str(j.get("progress", ""))[:10],
            str(j.get("created_at", ""))[:20],
        ])

    return format_table(headers, rows)


def format_job_detail(job: dict) -> str:
    """输出单个 job 详情（key: value 格式）。"""
    lines = []
    display_fields = [
        ("Job ID", "job_id"),
        ("Status", "status"),
        ("Source", "source"),
        ("Filename", "original_filename"),
        ("Progress", "progress"),
        ("Error", "error_message"),
        ("Created At", "created_at"),
        ("Updated At", "updated_at"),
    ]
    for label, key in display_fields:
        value = job.get(key, "")
        if value is None:
            value = ""
        lines.append(f"  {label:<14} {value}")

    return "\n".join(lines)


def format_job_output(jobs: list[dict] | dict, fmt: str = "table") -> str:
    """根据格式输出 job 数据。

    Args:
        jobs: job 列表或单个 job 字典
        fmt: 输出格式，"table" 或 "json"

    Returns:
        格式化后的字符串
    """
    if fmt == "json":
        return json.dumps(jobs, indent=2, default=str)

    if isinstance(jobs, list):
        return format_job_list(jobs)
    else:
        return format_job_detail(jobs)
