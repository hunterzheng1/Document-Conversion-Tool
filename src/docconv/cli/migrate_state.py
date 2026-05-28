"""JSON -> SQLite 状态迁移工具。

CLI 命令：docconv migrate-state --from <json_dir> --to <sqlite_path>

功能：
1. 扫描 JSON 目录下所有 *.json state 文件
2. 解析每个文件为 ConversionState
3. 提取 job_id（如无则生成占位 ID）
4. 批量写入 SQLite job_progress 表
5. 输出迁移报告

支持 --dry-run 预检模式。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class MigrationReport:
    """迁移报告。"""
    total_scanned: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0
    details: list[dict[str, Any]] = None

    def __post_init__(self):
        if self.details is None:
            self.details = []

    def add_success(self, file_path: str, job_id: str):
        self.success += 1
        self.details.append({
            "file": file_path,
            "job_id": job_id,
            "status": "success",
        })

    def add_failed(self, file_path: str, error: str):
        self.failed += 1
        self.details.append({
            "file": file_path,
            "error": error,
            "status": "failed",
        })

    def add_skipped(self, file_path: str, reason: str):
        self.skipped += 1
        self.details.append({
            "file": file_path,
            "reason": reason,
            "status": "skipped",
        })

    def summary(self) -> str:
        return (
            f"迁移完成: 扫描 {self.total_scanned} 个文件, "
            f"成功 {self.success}, 失败 {self.failed}, 跳过 {self.skipped}"
        )


def migrate_state(
    json_dir: str | Path,
    sqlite_path: str | Path,
    dry_run: bool = False,
    skip_no_job_id: bool = False,
) -> MigrationReport:
    """执行 JSON -> SQLite 状态迁移。

    Args:
        json_dir: JSON state 文件目录
        sqlite_path: 目标 SQLite 数据库路径
        dry_run: 预检模式，只输出报告不写入
        skip_no_job_id: 无 job_id 时是否跳过（False 则生成占位 ID）

    Returns:
        迁移报告
    """
    from docconv.infra.state_manager import ConversionState
    from docconv.service.state_repo import SQLiteStateRepository

    json_dir = Path(json_dir)
    sqlite_path = Path(sqlite_path)

    report = MigrationReport()

    if not json_dir.exists():
        report.add_failed(str(json_dir), "目录不存在")
        return report

    # 扫描所有 JSON 文件
    json_files = sorted(json_dir.glob("*.json"))
    report.total_scanned = len(json_files)

    if not json_files:
        return report

    # 初始化 SQLite 仓库（用于迁移）
    if not dry_run:
        repo = SQLiteStateRepository(data_dir=sqlite_path.parent)
    else:
        repo = None

    # 批量写入：每 100 条提交一次
    batch = []
    batch_size = 100

    for json_file in json_files:
        try:
            with open(json_file, encoding="utf-8") as f:
                data = json.load(f)

            state = ConversionState(**data)

            # 提取或生成 job_id
            job_id = state.job_id
            if not job_id:
                if skip_no_job_id:
                    report.add_skipped(
                        str(json_file), "无 job_id 且 skip_no_job_id=True"
                    )
                    continue
                job_id = f"migrated-{uuid.uuid4().hex[:8]}"

            if not dry_run and repo is not None:
                batch.append((state, job_id))

                # 每 batch_size 条提交一次
                if len(batch) >= batch_size:
                    _flush_batch(repo, batch, report, json_dir)
                    batch = []

            report.add_success(str(json_file), job_id)

        except (json.JSONDecodeError, TypeError, OSError) as e:
            report.add_failed(str(json_file), str(e))

    # 刷新剩余批次
    if not dry_run and repo is not None and batch:
        _flush_batch(repo, batch, report, json_dir)

    return report


def _flush_batch(
    repo,
    batch: list,
    report: MigrationReport,
    json_dir: Path,
):
    """将一批数据写入 SQLite。"""
    for state, job_id in batch:
        try:
            # 写入每页状态
            for page_num, page_data in state.pages.items():
                status = page_data.get("status", "pending")
                markdown = page_data.get("artifact") or ""
                error_type = page_data.get("error_type")
                errors = [error_type] if error_type else []

                repo.upsert_page(
                    job_id=job_id,
                    page_num=page_num,
                    status=status,
                    markdown=markdown,
                    errors=errors,
                )
        except Exception as e:
            # 找到对应的文件
            for detail in report.details:
                if detail.get("job_id") == job_id:
                    detail["status"] = "failed"
                    detail["error"] = str(e)
                    break
            report.success -= 1
            report.failed += 1
