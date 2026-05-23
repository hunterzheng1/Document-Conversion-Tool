"""PDF 解析自定义异常."""


class FileNotFoundError(Exception):
    """文件不存在."""

    def __init__(self, message: str = "文件不存在"):
        self.message = message
        super().__init__(self.message)


class PDFPasswordError(Exception):
    """PDF 密码错误或缺失."""

    def __init__(self, message: str = "PDF 需要密码"):
        self.message = message
        super().__init__(self.message)


class PDFParseError(Exception):
    """PDF 解析失败."""

    def __init__(self, message: str = "PDF 解析失败"):
        self.message = message
        super().__init__(self.message)


class PageRenderError(Exception):
    """页面渲染失败."""

    def __init__(self, message: str = "页面渲染失败"):
        self.message = message
        super().__init__(self.message)
