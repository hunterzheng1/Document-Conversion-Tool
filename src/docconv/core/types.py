"""核心类型定义。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PageContent:
    """单页转换结果。"""
    page_num: int
    page_type: str  # text_only, image_table, flowchart, diagram, mixed
    markdown: str
    images_processed: int = 0
    token_usage: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


@dataclass
class ConversionResult:
    """整个文档转换结果。"""
    file_path: str
    total_pages: int
    pages: list[PageContent] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    token_usage: dict = field(default_factory=dict)
    duration_seconds: float = 0.0

    @property
    def success_pages(self) -> int:
        return sum(1 for p in self.pages if not p.errors)

    @property
    def failed_pages(self) -> int:
        return sum(1 for p in self.pages if p.errors)

    @property
    def output_markdown(self) -> str:
        return "\n\n".join(p.markdown for p in self.pages if p.markdown)


@dataclass
class ConversionConfig:
    """转换配置。"""
    input_path: str = ""
    output_path: str = ""
    config_file: str = ""
    resume: bool = False
    parallel: int = 1
    verbose: bool = False
    sensitive_mode: bool = False
