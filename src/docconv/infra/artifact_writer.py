"""页级 artifact 原子写入器。

PageArtifactWriter 负责将页面转换结果（Markdown 和 meta.json）
原子写入到 job workspace 的 pages/ 目录。

使用 *.tmp + os.replace() 模式确保原子性，
写入失败时不残留部分文件。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from docconv.core.exceptions import ArtifactWriteError


class PageArtifactWriter:
    """页面产物原子写入器。

    目录结构：
        {workspace}/pages/
            page_0001.md
            page_0001.meta.json
            page_0002.md
            page_0002.meta.json
    """

    def __init__(self, workspace: str | Path):
        """初始化写入器。

        Args:
            workspace: job workspace 根目录
        """
        self._workspace = Path(workspace)
        self._pages_dir = self._workspace / "pages"
        self._pages_dir.mkdir(parents=True, exist_ok=True)

    def _page_path(self, page_num: int) -> Path:
        """获取页面 Markdown 文件路径。

        Args:
            page_num: 页号（必须为整数，从 1 开始）

        Returns:
            page_NNNN.md 路径

        Raises:
            ValueError: page_num 不是正整数
        """
        if not isinstance(page_num, int) or page_num < 1:
            raise ValueError(f"page_num 必须为正整数，得到: {page_num}")
        return self._pages_dir / f"page_{page_num:04d}.md"

    def _meta_path(self, page_num: int) -> Path:
        """获取页面 meta 文件路径。"""
        if not isinstance(page_num, int) or page_num < 1:
            raise ValueError(f"page_num 必须为正整数，得到: {page_num}")
        return self._pages_dir / f"page_{page_num:04d}.meta.json"

    def write_page(
        self,
        job_id: str,
        page_num: int,
        content: str,
        meta: dict[str, Any] | None = None,
    ) -> tuple[str, str]:
        """原子写入页面 Markdown 和 meta.json。

        使用 *.tmp + os.replace() 确保原子性。
        写入失败时回滚清理残留文件。

        Args:
            job_id: 任务 ID（用于日志和错误信息）
            page_num: 页号
            content: 页面 Markdown 内容
            meta: 页面元数据（可选）

        Returns:
            (markdown_path, meta_path) 元组

        Raises:
            ArtifactWriteError: 写入失败时抛出 ST5002
        """
        md_path = self._page_path(page_num)
        meta_path = self._meta_path(page_num)

        tmp_md = md_path.with_suffix(".md.tmp")
        tmp_meta = meta_path.with_suffix(".json.tmp")

        try:
            # 写入 Markdown
            with open(tmp_md, "w", encoding="utf-8") as f:
                f.write(content)

            # 写入 meta
            meta_data = meta or {
                "job_id": job_id,
                "page_num": page_num,
                "written_at": time.time(),
            }
            with open(tmp_meta, "w", encoding="utf-8") as f:
                json.dump(meta_data, f, ensure_ascii=False, indent=2)

            # 原子替换
            os.replace(tmp_md, md_path)
            os.replace(tmp_meta, meta_path)

            return (str(md_path), str(meta_path))

        except Exception as e:
            # 回滚清理残留临时文件
            for tmp in (tmp_md, tmp_meta):
                if tmp.exists():
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
            raise ArtifactWriteError(
                f"页面 {page_num} 写入失败 (job={job_id}): {e}"
            )

    def read_page(self, job_id: str, page_num: int) -> str | None:
        """读取页面 Markdown 内容。

        Args:
            job_id: 任务 ID
            page_num: 页号

        Returns:
            页面 Markdown 内容，文件不存在时返回 None
        """
        md_path = self._page_path(page_num)
        if not md_path.exists():
            return None
        with open(md_path, encoding="utf-8") as f:
            return f.read()

    def read_meta(self, job_id: str, page_num: int) -> dict[str, Any] | None:
        """读取页面元数据。

        Args:
            job_id: 任务 ID
            page_num: 页号

        Returns:
            页面元数据，文件不存在或解析失败时返回 None
        """
        meta_path = self._meta_path(page_num)
        if not meta_path.exists():
            return None
        try:
            with open(meta_path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def page_exists(self, job_id: str, page_num: int) -> bool:
        """检查页面 Markdown 文件是否存在。

        Args:
            job_id: 任务 ID
            page_num: 页号

        Returns:
            Markdown 文件是否存在
        """
        return self._page_path(page_num).exists()

    def delete_page(self, job_id: str, page_num: int) -> bool:
        """删除页面 artifact（Markdown + meta.json）。

        Args:
            job_id: 任务 ID
            page_num: 页号

        Returns:
            是否删除了文件（至少删除了一个）
        """
        md_path = self._page_path(page_num)
        meta_path = self._meta_path(page_num)
        deleted = False
        for p in (md_path, meta_path):
            if p.exists():
                p.unlink()
                deleted = True
        return deleted

    def list_pages(self, job_id: str) -> list[int]:
        """列出 workspace 中已有的页面号。

        Args:
            job_id: 任务 ID

        Returns:
            页面号列表（升序）
        """
        pages = []
        if not self._pages_dir.exists():
            return pages
        for f in self._pages_dir.glob("page_*.md"):
            if f.name.endswith(".md.tmp"):
                continue
            try:
                # page_NNNN.md -> NNNN
                num_str = f.stem.split("_")[1]
                pages.append(int(num_str))
            except (IndexError, ValueError):
                continue
        return sorted(pages)
