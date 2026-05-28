"""平台集成公共数据模型与适配协议。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# ---------------------------------------------------------------------------
# 平台枚举
# ---------------------------------------------------------------------------


class BotPlatform(str, Enum):
    """消息平台枚举。"""
    TELEGRAM = "telegram"
    FEISHU = "feishu"


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass
class BotMessage:
    """标准化 Bot 消息，屏蔽平台差异。

    包含 spec 中定义的全部 8 个字段。
    """
    platform: str  # "telegram" / "feishu"
    external_message_id: str  # 平台关联 ID
    chat_id: str  # 回传目标会话
    sender_id: str  # 发送者 ID
    file_id: str  # 平台文件 ID（用于下载）
    filename: str  # 文件展示名
    instruction: str  # 用户指令（如 /convert）
    job_id: str = ""  # 关联的转换任务 ID，创建后填充
    platform_meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class BotJobCorrelation:
    """Bot 消息与转换任务的关联记录。"""
    id: str = ""
    job_id: str = ""
    platform: str = ""
    external_message_id: str = ""
    chat_id: str = ""
    sender_id: str = ""
    created_at: str = ""
    updated_at: str = ""


# ---------------------------------------------------------------------------
# BotAdapter 抽象基类
# ---------------------------------------------------------------------------


class BotAdapter(ABC):
    """Bot 平台适配器抽象基类。

    各平台（Telegram、飞书）实现此基类，统一处理：
    - 来源验证（webhook 签名/secret 校验）
    - 消息解析（平台事件 -> BotMessage）
    - 文件下载
    - 结果回传
    - 错误通知（脱敏后）
    """

    @abstractmethod
    def verify_source(self, payload: dict) -> bool:
        """验证 webhook 请求来源。

        Args:
            payload: 平台原始事件载荷

        Returns:
            True 表示来源合法，False 表示拒绝
        """

    @abstractmethod
    def parse_message(self, payload: dict) -> BotMessage:
        """将平台原始事件解析为标准化 BotMessage。

        Args:
            payload: 平台原始事件载荷

        Returns:
            BotMessage 实例

        Raises:
            ValueError: 事件格式非法
        """

    @abstractmethod
    async def download_file(self, file_id: str, dest_path: str) -> str:
        """从平台下载文件到本地路径。

        Args:
            file_id: 平台文件 ID
            dest_path: 目标本地路径

        Returns:
            实际下载的本地文件路径
        """

    @abstractmethod
    async def send_result(self, chat_id: str, result_text: str, file_path: str = "") -> None:
        """发送转换结果到平台会话。

        Args:
            chat_id: 目标会话 ID
            result_text: Markdown 结果文本
            file_path: 结果文件路径（可选）
        """

    @abstractmethod
    async def send_failure(self, chat_id: str, job_id: str, error_summary: str) -> None:
        """发送脱敏失败摘要。

        Args:
            chat_id: 目标会话 ID
            job_id: 关联任务 ID
            error_summary: 脱敏后的失败摘要
        """

    @abstractmethod
    async def send_text(self, chat_id: str, text: str) -> None:
        """发送纯文本消息。

        Args:
            chat_id: 目标会话 ID
            text: 消息文本
        """
