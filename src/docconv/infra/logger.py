"""日志配置。"""

from __future__ import annotations

import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from .redaction import redact_text


class JSONFormatter(logging.Formatter):
    """结构化 JSON 日志格式化器。

    每条日志输出为一行合法 JSON，包含 timestamp、level、message、logger_name 字段。
    """

    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "message": redact_text(super().format(record)),
            "logger_name": record.name,
        }
        if record.exc_info and record.exc_info[0] is not None:
            log_obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_obj, ensure_ascii=False)


class _RedactingFormatter(logging.Formatter):
    """自动脱敏的日志格式化器（传统文本格式）。"""

    def __init__(self, fmt: str | None = None, datefmt: str | None = None):
        super().__init__(fmt=fmt, datefmt=datefmt)
        self._inner = logging.Formatter(fmt=fmt, datefmt=datefmt)

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        return redact_text(message)


def _is_json_format() -> bool:
    """检查是否启用 JSON 格式输出。"""
    return os.environ.get("LOG_FORMAT", "").lower() == "json"


def _create_handler(log_file: str | None) -> logging.Handler:
    """创建合适的 handler：有文件用 RotatingFileHandler，无文件用 StreamHandler。"""
    max_bytes = int(os.environ.get("LOG_MAX_BYTES", 10 * 1024 * 1024))  # 默认 10MB
    backup_count = int(os.environ.get("LOG_BACKUP_COUNT", 5))  # 默认 5 个备份

    if log_file:
        os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
        return RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
    return logging.StreamHandler(sys.stdout)


def setup_logger(
    name: str = "docconv",
    level: str | None = None,
    log_file: str | None = None,
) -> logging.Logger:
    """配置并返回 logger。

    - 自动避免重复添加 handler（多次调用不产生重复输出）。
    - 日志内容自动脱敏敏感信息。
    - 支持 LOG_FORMAT=json 启用 JSON 结构化输出。
    - 支持 LOG_FILE 指定日志文件，未设置时输出到 stdout。
    - 支持 LOG_MAX_BYTES（默认 10MB）和 LOG_BACKUP_COUNT（默认 5）控制日志轮转。
    """
    logger = logging.getLogger(name)

    # 从环境变量读取日志级别
    env_level = os.environ.get("LOG_LEVEL", level or "INFO").upper()
    logger.setLevel(getattr(logging, env_level, logging.INFO))

    # 避免重复 handler：如果已有 handler 则直接返回
    if logger.handlers:
        return logger

    # 根据配置选择格式化器
    if _is_json_format():
        formatter = JSONFormatter(datefmt="%Y-%m-%d %H:%M:%S")
    else:
        formatter = _RedactingFormatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    handler = _create_handler(log_file)
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger


def log_job_event(
    event: str,
    job_id: str,
    source: str,
    status: str = "",
    extra: dict | None = None,
    logger: logging.Logger | None = None,
) -> None:
    """记录任务生命周期事件的结构化日志。

    Args:
        event: 事件类型（created, claimed, completed, failed, cancelled, expired）
        job_id: 任务 ID
        source: 来源平台（cli, web, telegram, feishu）
        status: 任务状态（可选）
        extra: 额外字段（如 duration, page_count, error_type）
        logger: 使用的 logger（默认使用 docconv logger）
    """
    log = logger or logging.getLogger("docconv")
    log_obj = {
        "event": event,
        "job_id": job_id,
        "source": source,
    }
    if status:
        log_obj["status"] = status
    if extra:
        log_obj.update(extra)

    if event == "failed":
        log.warning("job_event: %s", json.dumps(log_obj, ensure_ascii=False))
    else:
        log.info("job_event: %s", json.dumps(log_obj, ensure_ascii=False))
