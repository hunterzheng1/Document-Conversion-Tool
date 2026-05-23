"""内容完整性验证器。"""

from __future__ import annotations


class ContentValidator:
    """验证输出内容的完整性。"""

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self._min_text_length = cfg.get("min_text_length", 10)
        self._max_page_errors = cfg.get("max_page_errors", 5)

    def validate_page(self, content: str, page_num: int) -> tuple[bool, list[str]]:
        """验证单页内容。

        Returns:
            (is_valid, errors) 元组
        """
        errors = []

        if not content.strip():
            errors.append(f"页码 {page_num}：内容为空")

        # 检查 Markdown 标记完整性
        if content.count("<!--") != content.count("-->"):
            errors.append(f"页码 {page_num}：HTML 注释不匹配")

        return len(errors) == 0, errors

    def validate_document(self, pages: list[dict]) -> tuple[bool, list[str]]:
        """验证整个文档的输出。

        Args:
            pages: [{"page_num": int, "content": str, "status": str}, ...]

        Returns:
            (is_valid, errors) 元组
        """
        all_errors = []

        for page in pages:
            valid, errors = self.validate_page(
                page.get("content", ""),
                page.get("page_num", 0),
            )
            all_errors.extend(errors)

        # 检查是否有过多页面失败
        if len(all_errors) > self._max_page_errors:
            all_errors.append(f"失败页面过多（{len(all_errors)} > {self._max_page_errors}）")

        return len(all_errors) == 0, all_errors
