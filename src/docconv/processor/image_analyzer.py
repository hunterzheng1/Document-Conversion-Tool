"""图片分析器：提取图片中的关键信息。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ImageAnalysisResult:
    """图片分析结果。"""
    ocr_text: str
    contains_table: bool
    contains_flowchart: bool
    contains_diagram: bool
    confidence: float


class ImageAnalyzer:
    """分析图片内容的分析器。"""

    def __init__(self, config: dict | None = None):
        self._config = config or {}

    async def analyze(self, image_path: str) -> ImageAnalysisResult:
        """分析单张图片。"""
        return ImageAnalysisResult(
            ocr_text="",
            contains_table=False,
            contains_flowchart=False,
            contains_diagram=False,
            confidence=0.0,
        )
