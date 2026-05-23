"""图片预处理模块：缩放、裁剪、去噪、增强。"""

from __future__ import annotations

from PIL import Image, ImageFilter, ImageEnhance


class ImagePreprocessor:
    """对图片进行标准化预处理，提升 OCR 质量。"""

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self._max_size = cfg.get("max_size", 2048)
        self._min_size = cfg.get("min_size", 64)
        self._denoise_strength = cfg.get("denoise_strength", 0.5)
        self._contrast_factor = cfg.get("contrast_factor", 1.2)
        self._grayscale = cfg.get("grayscale", True)

    def preprocess(self, image: Image.Image) -> Image.Image:
        """对图片执行预处理流水线。"""
        img = image

        # 缩放
        img = self._resize(img)

        # 灰度化
        if self._grayscale:
            img = img.convert("L")

        # 去噪
        if self._denoise_strength > 0:
            img = img.filter(ImageFilter.GaussianBlur(radius=self._denoise_strength))

        # 对比度增强
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(self._contrast_factor)

        return img

    def _resize(self, image: Image.Image) -> Image.Image:
        """按比例缩放图片，保持宽高比。"""
        w, h = image.size
        if w <= self._min_size and h <= self._min_size:
            return image

        scale = min(self._max_size / w, self._max_size / h, 1.0)
        if scale < 1.0:
            new_w = int(w * scale)
            new_h = int(h * scale)
            return image.resize((new_w, new_h), Image.LANCZOS)
        return image
