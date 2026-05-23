"""表格转换模块：将图片中的表格内容转为 Markdown 表格。"""

from __future__ import annotations


class TableConverter:
    """将图片中的表格转换为 Markdown 格式。"""

    def __init__(self, config: dict | None = None):
        self._config = config or {}

    async def convert(self, image_path: str, ocr_text: str = "") -> str:
        """将表格图片转换为 Markdown 表格。

        Args:
            image_path: 表格图片路径
            ocr_text: OCR 提取的文本内容

        Returns:
            Markdown 格式的表格字符串
        """
        # TODO: 接入视觉模型实现表格识别
        return ocr_text or ""
