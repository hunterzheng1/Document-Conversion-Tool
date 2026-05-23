"""文档转换器：主入口。"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from ..parser.pdf_parser import PDFParser
from ..infra.cache_manager import CacheManager
from ..infra.state_manager import StateManager, ConversionState
from ..infra.metrics import MetricsCollector
from .types import ConversionResult, PageContent
from .page_pipeline import PagePipeline

logger = logging.getLogger(__name__)


class DocumentConverter:
    """PDF 转 Markdown 文档转换器。"""

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self._config = cfg
        self._pipeline = PagePipeline(cfg)
        self._cache = CacheManager(cfg.get("cache", {}))
        self._state_mgr = StateManager(cfg.get("state", {}))
        self._metrics = MetricsCollector()

    async def convert(self, file_path: str, resume: bool = False) -> ConversionResult:
        """执行转换。

        Args:
            file_path: PDF 文件路径
            resume: 是否断点续传

        Returns:
            ConversionResult 转换结果
        """
        self._metrics.start()
        start_time = time.time()

        result = ConversionResult(file_path=file_path, total_pages=0)

        with PDFParser(file_path) as parser:
            total_pages = parser.get_page_count()
            result.total_pages = total_pages

            state = None
            if resume:
                state = self._state_mgr.load(file_path)
                logger.info(f"断点续传：已完成 {len(state.completed_pages)}/{total_pages} 页")

            tasks = []
            for i in range(total_pages):
                if state and i in state.completed_pages:
                    logger.debug(f"跳过已完成页面 {i + 1}")
                    continue
                tasks.append(self._process_page_with_cache(parser, i, file_path))

            # 并行处理
            page_results = await asyncio.gather(*tasks, return_exceptions=True)

            for item in page_results:
                if isinstance(item, Exception):
                    logger.error(f"页面处理失败: {item}")
                    result.errors.append(str(item))
                elif isinstance(item, PageContent):
                    result.pages.append(item)

        # 按页码排序
        result.pages.sort(key=lambda p: p.page_num)
        result.duration_seconds = time.time() - start_time

        self._metrics.stop()
        self._metrics.record_file_completed(len(result.pages))

        if resume and state:
            state.status = "completed"
            state.completed_pages = [p.page_num - 1 for p in result.pages]
            self._state_mgr.save(state)

        logger.info(f"转换完成: {len(result.pages)}/{result.total_pages} 页，耗时 {result.duration_seconds:.1f}s")
        return result

    async def _process_page_with_cache(
        self,
        parser: PDFParser,
        page_num: int,
        file_path: str,
    ) -> PageContent:
        """带缓存的页面处理。"""
        cache_key = f"{file_hash(file_path)}_page_{page_num}"
        cached = self._cache.get(cache_key)

        if cached:
            logger.debug(f"缓存命中：页面 {page_num + 1}")
            return PageContent(**cached)

        page = await self._pipeline.process_page(parser, page_num)

        self._cache.set(cache_key, {
            "page_num": page.page_num,
            "page_type": page.page_type,
            "markdown": page.markdown,
            "images_processed": page.images_processed,
            "token_usage": page.token_usage,
            "errors": page.errors,
        })

        return page


def file_hash(path: str) -> str:
    import hashlib
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
