"""PDF 解析器，基于 PyMuPDF (fitz)。"""

from __future__ import annotations

import os
from io import BytesIO
from typing import Generator

import fitz  # PyMuPDF
from PIL import Image

from .errors import FileNotFoundError, PDFPasswordError, PDFParseError, PageRenderError


class PDFParser:
    """PDF 解析器。"""

    def __init__(self, file_path: str, dpi: int = 200, password: str | None = None):
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        self._file_path = file_path
        self._dpi = dpi

        try:
            self._doc = fitz.open(file_path)
        except Exception as e:
            raise PDFParseError(f"无法打开 PDF: {e}") from e

        if self._doc.is_encrypted:
            if password:
                if not self._doc.authenticate(password):
                    raise PDFPasswordError("密码错误")
            else:
                raise PDFPasswordError("PDF 需要密码，请使用 password 参数")

        self._metadata_cache: dict | None = None

    def get_metadata(self) -> dict:
        if self._metadata_cache:
            return self._metadata_cache

        meta = self._doc.metadata or {}
        self._metadata_cache = {
            "title": meta.get("title", ""),
            "author": meta.get("author", ""),
            "pages": self._doc.page_count,
            "encrypted": self._doc.is_encrypted,
            "size_bytes": os.path.getsize(self._file_path),
        }
        return self._metadata_cache

    def get_page_count(self) -> int:
        return self._doc.page_count

    def extract_text(self, page_num: int) -> str:
        if page_num < 0 or page_num >= self._doc.page_count:
            raise PageRenderError(f"页码越界: {page_num}, 总页数: {self._doc.page_count}")
        page = self._doc.load_page(page_num)
        return page.get_text("text")

    def get_images(self, page_num: int) -> list:
        if page_num < 0 or page_num >= self._doc.page_count:
            raise PageRenderError(f"页码越界: {page_num}, 总页数: {self._doc.page_count}")
        page = self._doc.load_page(page_num)
        return page.get_images(full=True)

    def render_page(self, page_num: int, dpi: int | None = None) -> Image:
        if page_num < 0 or page_num >= self._doc.page_count:
            raise PageRenderError(f"页码越界: {page_num}, 总页数: {self._doc.page_count}")

        dpi = dpi or self._dpi
        page = self._doc.load_page(page_num)
        pixmap = page.get_pixmap(dpi=dpi)
        return Image.open(BytesIO(pixmap.tobytes("png")))

    def iter_pages(self) -> Generator[dict, None, None]:
        for i in range(self._doc.page_count):
            text = self.extract_text(i)
            images = self.get_images(i)
            yield {"page_num": i, "text": text, "images": images}

    def close(self):
        if self._doc:
            self._doc.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
