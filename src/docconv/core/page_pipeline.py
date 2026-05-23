"""页面处理流水线：编排分类、提取、转换步骤。"""

from __future__ import annotations

import logging
from typing import Any

from ..parser.pdf_parser import PDFParser
from ..processor.page_classifier import PageClassifier, PageType
from ..processor.text_processor import TextProcessor
from ..processor.image_preprocessor import ImagePreprocessor
from ..processor.image_analyzer import ImageAnalyzer
from ..processor.table_converter import TableConverter
from ..processor.mermaid_converter import MermaidConverter
from .types import PageContent

logger = logging.getLogger(__name__)


class PagePipeline:
    """页面处理流水线。"""

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self._classifier = PageClassifier(cfg.get("classification", {}))
        self._text_processor = TextProcessor(cfg.get("text_processing", {}))
        self._image_preprocessor = ImagePreprocessor(cfg.get("image", {}))
        self._image_analyzer = ImageAnalyzer(cfg.get("image_analysis", {}))
        self._table_converter = TableConverter(cfg.get("table_conversion", {}))
        self._mermaid_converter = MermaidConverter(cfg.get("mermaid_conversion", {}))

    async def process_page(
        self,
        parser: PDFParser,
        page_num: int,
    ) -> PageContent:
        """处理单页 PDF。"""
        errors = []
        images_processed = 0

        # 提取文本
        text = parser.extract_text(page_num)
        images = parser.get_images(page_num)
        image_count = len(images)

        # 分类页面
        classification = self._classifier.classify_page(text, image_count)

        if classification.page_type == PageType.TEXT_ONLY:
            # 纯文本页面
            markdown = self._text_processor.format(text, page_num + 1)

        elif classification.page_type == PageType.IMAGE_TABLE:
            # 表格图片页面
            markdown = await self._handle_table_page(parser, page_num, text, images)
            images_processed = image_count

        elif classification.page_type in (PageType.FLOWCHART, PageType.DIAGRAM):
            # 流程图/图表页面
            markdown = await self._handle_flowchart_page(parser, page_num, text, images)
            images_processed = image_count

        elif classification.page_type == PageType.MIXED:
            # 混合页面
            markdown = await self._handle_mixed_page(parser, page_num, text, images)
            images_processed = image_count

        else:
            # 未知类型，当作纯文本处理
            markdown = self._text_processor.format(text, page_num + 1)

        return PageContent(
            page_num=page_num + 1,
            page_type=classification.page_type,
            markdown=markdown,
            images_processed=images_processed,
            errors=errors,
        )

    async def _handle_table_page(
        self,
        parser: PDFParser,
        page_num: int,
        text: str,
        images: list,
    ) -> str:
        """处理含表格的页面。"""
        if not images:
            return self._text_processor.format(text, page_num + 1)

        # 渲染第一张图片
        pil_image = parser.render_page(page_num)
        preprocessed = self._image_preprocessor.preprocess(pil_image)

        # 保存图片并调用表格转换
        import tempfile
        import os
        tmp_path = os.path.join(tempfile.gettempdir(), f"page_{page_num}.png")
        preprocessed.save(tmp_path)

        table_md = await self._table_converter.convert(tmp_path)
        os.remove(tmp_path)

        header = f"<!-- page: {page_num + 1} type: image_table status: completed -->\n\n"
        return header + (table_md or text)

    async def _handle_flowchart_page(
        self,
        parser: PDFParser,
        page_num: int,
        text: str,
        images: list,
    ) -> str:
        """处理流程图页面。"""
        import tempfile
        import os
        tmp_path = os.path.join(tempfile.gettempdir(), f"page_{page_num}.png")

        pil_image = parser.render_page(page_num)
        preprocessed = self._image_preprocessor.preprocess(pil_image)
        preprocessed.save(tmp_path)

        mermaid_md = await self._mermaid_converter.convert(tmp_path)
        os.remove(tmp_path)

        if mermaid_md:
            # 包装为 Mermaid 代码块
            if "```mermaid" not in mermaid_md:
                mermaid_md = f"```mermaid\n{mermaid_md}\n```"

        header = f"<!-- page: {page_num + 1} type: flowchart status: completed -->\n\n"
        return header + (mermaid_md or text)

    async def _handle_mixed_page(
        self,
        parser: PDFParser,
        page_num: int,
        text: str,
        images: list,
    ) -> str:
        """处理混合内容页面。"""
        text_md = self._text_processor.format(text, page_num + 1)

        # 如果有图片，附加图片分析结果
        if images:
            import tempfile
            import os
            tmp_path = os.path.join(tempfile.gettempdir(), f"page_{page_num}.png")

            pil_image = parser.render_page(page_num)
            preprocessed = self._image_preprocessor.preprocess(pil_image)
            preprocessed.save(tmp_path)

            # 分析图片
            analysis = await self._image_analyzer.analyze(tmp_path)
            os.remove(tmp_path)

            if analysis.ocr_text:
                text_md += f"\n\n<!-- 图片OCR: {analysis.ocr_text[:200]} -->"

        return text_md
