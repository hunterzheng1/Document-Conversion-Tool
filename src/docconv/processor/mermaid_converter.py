"""Mermaid 转换模块：将流程图/架构图图片转为 Mermaid 代码。"""

from __future__ import annotations


class MermaidConverter:
    """将流程图/架构图图片转换为 Mermaid 图表语法。"""

    def __init__(self, config: dict | None = None):
        self._config = config or {}

    async def convert(self, image_path: str, ocr_text: str = "") -> str:
        """将流程图图片转换为 Mermaid 代码。

        Args:
            image_path: 流程图图片路径
            ocr_text: OCR 提取的文本内容

        Returns:
            Mermaid 格式的图表字符串
        """
        # TODO: 接入视觉模型实现流程图识别
        return ocr_text or ""
