"""页面类型分类器."""

from __future__ import annotations
from dataclasses import dataclass


class PageType:
    TEXT_ONLY = "text_only"
    IMAGE_TABLE = "image_table"
    FLOWCHART = "flowchart"
    DIAGRAM = "diagram"
    MIXED = "mixed"
    UNKNOWN = "unknown"


@dataclass
class ClassificationResult:
    page_type: str
    confidence: float
    reasons: list[str]


DEFAULT_TABLE_KEYWORDS = ["表格", "字段", "说明", "权限", "状态", "编号", "金额", "合计", "table", "field"]
DEFAULT_FLOWCHART_KEYWORDS = ["开始", "结束", "判断", "审批", "状态流转", "节点", "流程", "步骤"]


class PageClassifier:
    """基于规则判断页面类型。"""

    def __init__(self, config: dict | None = None):
        config = config or {}
        self._table_keywords = config.get("table_keywords", DEFAULT_TABLE_KEYWORDS)
        self._flowchart_keywords = config.get("flowchart_keywords", DEFAULT_FLOWCHART_KEYWORDS)

    def classify_page(self, text: str, image_count: int) -> ClassificationResult:
        reasons = []

        if len(text or "") < 10 and image_count == 0:
            return ClassificationResult(page_type=PageType.UNKNOWN, confidence=0.5, reasons=["空页"])

        has_table = any(kw in (text or "") for kw in self._table_keywords)
        has_flow = any(kw in (text or "") for kw in self._flowchart_keywords)

        if image_count == 0 and len(text or "") > 200:
            return ClassificationResult(page_type=PageType.TEXT_ONLY, confidence=0.9, reasons=["纯文本，无图片"])

        if has_table and image_count > 0:
            return ClassificationResult(page_type=PageType.IMAGE_TABLE, confidence=0.7, reasons=["含表格关键词"])

        if has_flow and image_count > 0:
            return ClassificationResult(page_type=PageType.FLOWCHART, confidence=0.7, reasons=["含流程关键词"])

        if image_count > 0:
            return ClassificationResult(page_type=PageType.MIXED, confidence=0.6, reasons=["含图片"])

        return ClassificationResult(page_type=PageType.UNKNOWN, confidence=0.3, reasons=["无法判断"])
