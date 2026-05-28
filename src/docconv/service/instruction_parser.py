"""指令白名单解析器。

从 Bot 消息文本中解析出结构化转换参数。
仅允许白名单内的指令和参数，非白名单指令被拒绝。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# 指令最大长度（字符）
INSTRUCTION_MAX_LENGTH = 1000

# 支持的敏感模式关键字
SENSITIVE_KEYWORDS = {"敏感模式", "sensitive", "敏感"}

# 支持的模型档位关键字
MODEL_KEYWORDS = {
    "fast": "fast",
    "标准": "standard",
    "standard": "standard",
    "高质量": "high",
    "high": "high",
}

# 支持的输出格式关键字
OUTPUT_FORMAT_KEYWORDS = {
    "markdown": "markdown",
    "转成 markdown": "markdown",
    "转成markdown": "markdown",
    "转成 Markdown": "markdown",
    "转成Markdown": "markdown",
}


@dataclass
class ParsedInstruction:
    """解析后的指令结果。"""
    action: str  # "convert", "status", "cancel", "help", "unknown"
    options: dict[str, Any] = field(default_factory=dict)
    help_text: str = ""
    rejected: bool = False
    reject_reason: str = ""


class InstructionParser:
    """白名单指令解析器。

    解析来自 Bot 的文本指令，仅允许：
    - 转换相关：/convert + 可选参数
    - 状态查询：/status
    - 取消任务：/cancel
    - 帮助：/help

    拒绝所有非白名单指令（如 shell 命令、路径操作等）。
    """

    # 危险指令模式（直接拒绝）
    DANGEROUS_PATTERNS = [
        re.compile(r'^[./]*\s*(rm|del|rmdir|chmod|chown|sudo|curl|wget|eval|exec)\b', re.IGNORECASE),
        re.compile(r'[;|&`\$]'),  # shell 元字符
        re.compile(r'^\s*/\.\.'),  # 路径穿越
    ]

    def parse(self, text: str) -> ParsedInstruction:
        """解析指令文本。

        Args:
            text: 用户输入的文本

        Returns:
            ParsedInstruction 解析结果
        """
        if not text:
            return ParsedInstruction(action="unknown", help_text=self._help())

        # 长度检查
        if len(text) > INSTRUCTION_MAX_LENGTH:
            return ParsedInstruction(
                action="unknown",
                rejected=True,
                reject_reason=f"指令长度超过 {INSTRUCTION_MAX_LENGTH} 字符限制",
                help_text=self._help(),
            )

        # 危险指令检查
        if self._is_dangerous(text):
            return ParsedInstruction(
                action="unknown",
                rejected=True,
                reject_reason="不支持的指令",
                help_text=self._help(),
            )

        stripped = text.strip()

        # 命令按钮
        if stripped in ("/help", "/start"):
            return ParsedInstruction(action="help", help_text=self._help())

        if stripped == "/status":
            return ParsedInstruction(action="status")

        if stripped == "/cancel":
            return ParsedInstruction(action="cancel")

        if stripped == "/convert":
            return ParsedInstruction(action="convert")

        # /convert + 参数
        if stripped.startswith("/convert "):
            return self._parse_convert(stripped[len("/convert "):])

        # 纯文本指令（不带 / 前缀）
        return self._parse_plain_text(stripped)

    def _parse_convert(self, params_text: str) -> ParsedInstruction:
        """解析 /convert 后面的参数。

        支持的参数：
        - 敏感模式关键字
        - 模型档位关键字
        - DPI 设置（如 dpi=300）
        - dry-run 模式
        - 输出格式
        """
        options: dict[str, Any] = {}
        lower = params_text.lower()

        # 检查输出格式
        for keyword, fmt in OUTPUT_FORMAT_KEYWORDS.items():
            if keyword.lower() in params_text.lower():
                options["output_format"] = fmt
                break

        # 检查敏感模式
        for kw in SENSITIVE_KEYWORDS:
            if kw.lower() in lower:
                options["sensitive_mode"] = True
                break

        # 检查模型档位
        for kw, model in MODEL_KEYWORDS.items():
            if kw.lower() in lower:
                options["model"] = model
                break

        # 检查 DPI
        dpi_match = re.search(r'dpi\s*[:=]?\s*(\d+)', params_text, re.IGNORECASE)
        if dpi_match:
            options["dpi"] = int(dpi_match.group(1))

        # 检查 dry-run
        if "dry-run" in lower or "dry_run" in lower or "预检" in params_text:
            options["dry_run"] = True

        return ParsedInstruction(action="convert", options=options)

    def _parse_plain_text(self, text: str) -> ParsedInstruction:
        """解析纯文本（不带 / 前缀）指令。"""
        lower = text.lower()

        # 包含转换关键词
        if any(kw in lower for kw in ["转换", "转成", "convert", "markdown"]):
            return self._parse_convert(text)

        # 检查是否包含 shell 风格命令
        for pattern in self.DANGEROUS_PATTERNS:
            if pattern.search(text):
                return ParsedInstruction(
                    action="unknown",
                    rejected=True,
                    reject_reason="不支持的指令",
                    help_text=self._help(),
                )

        return ParsedInstruction(
            action="unknown",
            rejected=True,
            reject_reason="无法识别的指令",
            help_text=self._help(),
        )

    def _is_dangerous(self, text: str) -> bool:
        """检查是否包含危险指令。"""
        for pattern in self.DANGEROUS_PATTERNS:
            if pattern.search(text):
                return True
        return False

    def _help(self) -> str:
        """返回帮助文本。"""
        return (
            "支持的指令：\n"
            "/convert - 上传 PDF 文件开始转换\n"
            "  可选参数：敏感模式、模型档位(fast/standard/high)、dpi=300、dry-run\n"
            "/status - 查看当前任务状态\n"
            "/cancel - 取消当前任务\n"
            "/help - 显示此帮助信息"
        )
