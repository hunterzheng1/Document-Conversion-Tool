"""Bot 适配器抽象基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class BotMessage:
    """标准化 Bot 消息，屏蔽平台差异。"""
    platform: str  # "telegram" / "feishu"
    user_id: str
    chat_id: str
    text: str
    file_url: str = ""  # 文件下载 URL 或本地路径
    file_name: str = ""
    platform_meta: dict[str, Any] | None = None


class BotAdapter(ABC):
    """Bot 平台适配器接口。"""

    @abstractmethod
    async def handle_message(self, message: BotMessage) -> None:
        """处理来自用户的消息。

        职责：
        1. 解析指令（convert / status / cancel）
        2. 下载附件（如果有）
        3. 调用 ConversionJobService 创建任务
        4. 轮询任务状态并回传结果
        """

    @abstractmethod
    async def send_text(self, chat_id: str, text: str) -> None:
        """发送文本消息。"""

    @abstractmethod
    async def send_file(self, chat_id: str, file_path: str, caption: str = "") -> None:
        """发送文件。"""

    @abstractmethod
    async def send_error(self, chat_id: str, error_message: str) -> None:
        """发送错误消息（脱敏后）。"""

    @abstractmethod
    async def start_polling(self) -> None:
        """启动消息轮询。"""

    @abstractmethod
    async def stop_polling(self) -> None:
        """停止消息轮询。"""
