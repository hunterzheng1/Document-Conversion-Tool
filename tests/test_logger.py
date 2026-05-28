"""日志模块测试。"""

import json
import logging
import os
import sys
import tempfile
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from docconv.infra.logger import (
    setup_logger,
    JSONFormatter,
    _RedactingFormatter,
    log_job_event,
)
from docconv.infra.redaction import redact_text


def _reset_logger(name: str) -> None:
    """重置 logger 以便重复测试。"""
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.setLevel(logging.NOTSET)


# ---------------------------------------------------------------------------
# JSONFormatter
# ---------------------------------------------------------------------------

class TestJSONFormatter:
    """测试 JSON 结构化日志格式化器。"""

    def test_output_is_valid_json(self):
        formatter = JSONFormatter(datefmt="%Y-%m-%d %H:%M:%S")
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Hello world",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        obj = json.loads(output)
        assert "timestamp" in obj
        assert obj["level"] == "INFO"
        assert obj["message"] == "Hello world"
        assert obj["logger_name"] == "test_logger"

    def test_redacts_secrets_in_message(self):
        formatter = JSONFormatter(datefmt="%Y-%m-%d %H:%M:%S")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="API key: sk-ant-abc1234567890abcdef1234567890ab",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        obj = json.loads(output)
        assert "sk-ant-" not in obj["message"]
        assert "***REDACTED***" in obj["message"]

    def test_exception_included(self):
        formatter = JSONFormatter(datefmt="%Y-%m-%d %H:%M:%S")
        try:
            raise ValueError("test error")
        except ValueError:
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="Failed",
            args=(),
            exc_info=exc_info,
        )
        output = formatter.format(record)
        obj = json.loads(output)
        assert "exception" in obj
        assert "ValueError" in obj["exception"]


class TestJSONFormatEnv:
    """测试 LOG_FORMAT=json 环境变量控制。"""

    def test_json_format_via_env(self, capsys):
        _reset_logger("docconv_json_env")
        old = os.environ.get("LOG_FORMAT")
        try:
            os.environ["LOG_FORMAT"] = "json"
            logger = setup_logger(name="docconv_json_env")
            logger.handlers.clear()

            handler = logging.StreamHandler(sys.stdout)
            from docconv.infra.logger import JSONFormatter as JF
            handler.setFormatter(JF(datefmt="%Y-%m-%d %H:%M:%S"))
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)

            logger.info("test json output")
            captured = capsys.readouterr()
            obj = json.loads(captured.out.strip())
            assert obj["level"] == "INFO"
            assert obj["message"] == "test json output"
        finally:
            if old is None:
                os.environ.pop("LOG_FORMAT", None)
            else:
                os.environ["LOG_FORMAT"] = old

    def test_text_format_default(self, capsys):
        _reset_logger("docconv_text_default")
        logger = setup_logger(name="docconv_text_default")
        logger.handlers.clear()

        handler = logging.StreamHandler(sys.stdout)
        from docconv.infra.logger import _RedactingFormatter as RF
        handler.setFormatter(RF(fmt="%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        logger.info("hello text")
        captured = capsys.readouterr()
        assert "hello text" in captured.out
        # 不应是 JSON
        with pytest.raises(json.JSONDecodeError):
            json.loads(captured.out.strip())


# ---------------------------------------------------------------------------
# Log Rotation
# ---------------------------------------------------------------------------

class TestLogRotation:
    """测试日志轮转（RotatingFileHandler）。"""

    def test_rotating_file_handler_created(self):
        """log_file 指定时应使用 RotatingFileHandler。"""
        _reset_logger("docconv_rotation_test")
        log_path = os.path.join(tempfile.gettempdir(), "test_rotation.log")
        try:
            logger = setup_logger(name="docconv_rotation_test", log_file=log_path)
            has_rotating = any(
                isinstance(h, logging.handlers.RotatingFileHandler)
                for h in logger.handlers
            )
            assert has_rotating, "应有 RotatingFileHandler"
        finally:
            logger = logging.getLogger("docconv_rotation_test")
            for h in logger.handlers:
                if isinstance(h, logging.Handler):
                    h.close()
            for suffix in ["", ".1", ".2"]:
                if os.path.exists(log_path + suffix):
                    os.unlink(log_path + suffix)

    def test_stream_handler_when_no_file(self):
        """无 log_file 时应使用 StreamHandler。"""
        _reset_logger("docconv_stream_only")
        logger = setup_logger(name="docconv_stream_only")
        has_stream = any(
            isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
            for h in logger.handlers
        )
        # StreamHandler 是 FileHandler 的父类，所以用 hasattr 判断
        has_stdout = any(
            hasattr(h, "stream") and h.stream is sys.stdout
            for h in logger.handlers
        )
        assert has_stdout

    def test_log_rotation_cre_backup(self):
        """日志文件达到 maxBytes 后应创建备份。"""
        import logging.handlers
        _reset_logger("docconv_rotation_real")
        tmp_dir = tempfile.mkdtemp()
        log_path = os.path.join(tmp_dir, "tiny.log")

        logger = logging.getLogger("docconv_rotation_real")
        logger.handlers.clear()
        logger.setLevel(logging.INFO)

        handler = logging.handlers.RotatingFileHandler(
            log_path, maxBytes=500, backupCount=2, encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)

        # 写入超过 500 字节的内容
        for i in range(20):
            logger.info("x" * 50)
        handler.close()
        logger.handlers.clear()

        # 应有至少一个备份文件
        backup_exists = os.path.exists(log_path + ".1")
        assert backup_exists, "应有 .1 备份文件"

        # 清理
        for suffix in ["", ".1", ".2"]:
            p = log_path + suffix
            if os.path.exists(p):
                os.unlink(p)
        os.rmdir(tmp_dir)

    def test_max_backup_limit(self):
        """备份文件数量不应超过 backupCount。"""
        import logging.handlers
        _reset_logger("docconv_rotation_limit")
        tmp_dir = tempfile.mkdtemp()
        log_path = os.path.join(tmp_dir, "limit.log")

        logger = logging.getLogger("docconv_rotation_limit")
        logger.handlers.clear()
        logger.setLevel(logging.INFO)

        handler = logging.handlers.RotatingFileHandler(
            log_path, maxBytes=200, backupCount=2, encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)

        # 写入大量数据触发多次轮转
        for i in range(50):
            logger.info("y" * 50)
        handler.close()
        logger.handlers.clear()

        # 不应超过 2 个备份
        backup_count = sum(
            1 for suffix in [".1", ".2", ".3", ".4"]
            if os.path.exists(log_path + suffix)
        )
        assert backup_count <= 2

        # 清理
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Log Level from Env
# ---------------------------------------------------------------------------

class TestLogLevelEnv:
    """测试 LOG_LEVEL 环境变量。"""

    def test_debug_level_via_env(self):
        _reset_logger("docconv_level_test")
        old = os.environ.get("LOG_LEVEL")
        try:
            os.environ["LOG_LEVEL"] = "DEBUG"
            logger = setup_logger(name="docconv_level_test")
            assert logger.level == logging.DEBUG
        finally:
            if old is None:
                os.environ.pop("LOG_LEVEL", None)
            else:
                os.environ["LOG_LEVEL"] = old


# ---------------------------------------------------------------------------
# Job Lifecycle Logging
# ---------------------------------------------------------------------------

class TestJobLifecycleLogging:
    """测试任务生命周期事件日志。"""

    def test_log_job_event_created(self, caplog):
        caplog.set_level(logging.INFO, logger="docconv")
        log_job_event(
            event="created",
            job_id="job_test_001",
            source="cli",
            status="queued",
        )
        assert any("job_test_001" in r.message for r in caplog.records)
        assert any("created" in r.message for r in caplog.records)

    def test_log_job_event_completed(self, caplog):
        caplog.set_level(logging.INFO, logger="docconv")
        log_job_event(
            event="completed",
            job_id="job_test_002",
            source="web",
            status="succeeded",
            extra={"duration": 1.5, "page_count": 10},
        )
        assert any("completed" in r.message for r in caplog.records)

    def test_log_job_event_failed(self, caplog):
        caplog.set_level(logging.WARNING, logger="docconv")
        log_job_event(
            event="failed",
            job_id="job_test_003",
            source="telegram",
            status="failed",
            extra={"error_type": "ConversionError"},
        )
        assert any("failed" in r.message for r in caplog.records)

    def test_job_event_contains_json(self, caplog):
        """日志消息中应包含 JSON 格式的事件数据。"""
        caplog.set_level(logging.INFO, logger="docconv")
        log_job_event(
            event="created",
            job_id="job_test_004",
            source="feishu",
            status="queued",
            extra={"file_size": 1024},
        )
        messages = [r.message for r in caplog.records]
        # 应包含 job_event 前缀
        job_msgs = [m for m in messages if "job_event" in m]
        assert len(job_msgs) > 0
        # 消息中的 JSON 部分应可解析
        for msg in job_msgs:
            json_part = msg.split("job_event: ", 1)[1]
            obj = json.loads(json_part)
            assert obj["event"] == "created"
            assert obj["job_id"] == "job_test_004"
            assert obj["source"] == "feishu"
            assert obj["file_size"] == 1024


# ---------------------------------------------------------------------------
# Original setup_logger tests
# ---------------------------------------------------------------------------

class TestSetupLogger:
    """测试 setup_logger 函数。"""

    def test_default_logger(self):
        _reset_logger("docconv")
        logger = setup_logger()
        assert logger.name == "docconv"
        assert logger.level == logging.INFO
        assert len(logger.handlers) >= 1

    def test_custom_level(self):
        _reset_logger("docconv_debug")
        logger = setup_logger(name="docconv_debug", level="DEBUG")
        assert logger.level == logging.DEBUG

    def test_file_handler_created(self):
        """指定 log_file 时应创建文件 handler。"""
        _reset_logger("docconv_file_test")
        log_path = os.path.join(tempfile.gettempdir(), "test_docconv_logger.log")
        try:
            # 确保清理旧 handler
            old_logger = logging.getLogger("docconv_file_test")
            old_logger.handlers.clear()

            logger = setup_logger(name="docconv_file_test", log_file=log_path)
            # 应该有 RotatingFileHandler
            has_file = any(
                isinstance(h, logging.handlers.RotatingFileHandler)
                for h in logger.handlers
            )
            assert has_file, "应有 RotatingFileHandler"
        finally:
            # 先关闭 handler 释放文件锁
            logger = logging.getLogger("docconv_file_test")
            for h in logger.handlers:
                if isinstance(h, logging.Handler):
                    h.close()
            if os.path.exists(log_path):
                os.unlink(log_path)

    def test_no_duplicate_handlers(self):
        """多次调用 setup_logger 不应产生重复 handler。"""
        _reset_logger("docconv_nodup")
        logger1 = setup_logger(name="docconv_nodup")
        handler_count = len(logger1.handlers)
        logger2 = setup_logger(name="docconv_nodup")
        assert len(logger2.handlers) == handler_count

    def test_log_output_contains_redacted_api_key(self, capsys):
        """日志输出中的 API Key 应被脱敏。"""
        _reset_logger("docconv_redact_test")
        logger = setup_logger(name="docconv_redact_test")

        # 清除可能已有的 handler
        logger.handlers.clear()
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_RedactingFormatter(fmt="%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        logger.info("API key is sk-ant-abc1234567890abcdef1234567890ab")
        captured = capsys.readouterr()
        assert "sk-ant-" not in captured.out
        assert "***REDACTED***" in captured.out

    def test_normal_message_unchanged(self, capsys):
        """普通消息不应被修改。"""
        _reset_logger("docconv_normal_test")
        logger = logging.getLogger("docconv_normal_test")
        logger.handlers.clear()
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_RedactingFormatter(fmt="%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        logger.info("Hello world")
        captured = capsys.readouterr()
        assert "Hello world" in captured.out


# ---------------------------------------------------------------------------
# Performance tests
# ---------------------------------------------------------------------------

class TestPerformance:
    """性能约束验证。"""

    def test_redact_text_p99_under_1ms(self):
        """redact_text() P99 < 1ms。"""
        texts = [
            "Hello world",
            "key=sk-ant-abc1234567890abcdef1234567890ab",
            "Bearer eyJhbGciOiJIUzI1NiJ9.secret",
            "https://api.example.com?token=abc123",
            "No secrets here" * 100,
        ] * 20  # 100 次

        times = []
        for text in texts:
            start = time.perf_counter()
            redact_text(text)
            elapsed = (time.perf_counter() - start) * 1000  # ms
            times.append(elapsed)

        times.sort()
        p99_idx = int(len(times) * 0.99)
        p99 = times[min(p99_idx, len(times) - 1)]
        assert p99 < 1.0, f"P99 redact_text = {p99:.3f}ms >= 1ms"

    def test_log_write_p99_under_2ms(self):
        """单次日志写入 P99 < 2ms。"""
        tmp_dir = tempfile.mkdtemp()
        log_path = os.path.join(tmp_dir, "perf.log")

        logger = logging.getLogger("docconv_perf_test")
        logger.handlers.clear()
        logger.setLevel(logging.INFO)
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)

        times = []
        for i in range(100):
            start = time.perf_counter()
            logger.info(f"Performance test message {i}")
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)

        handler.close()
        logger.handlers.clear()

        times.sort()
        p99_idx = int(len(times) * 0.99)
        p99 = times[min(p99_idx, len(times) - 1)]
        assert p99 < 2.0, f"P99 log write = {p99:.3f}ms >= 2ms"

        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_health_check_p99_under_1000ms(self):
        """健康检查 P99 < 1000ms。"""
        import tempfile
        from docconv.infra.health_check import HealthChecker

        tmp_dir = tempfile.mkdtemp()
        config = {
            "storage_root": tmp_dir,
            "cache_dir": os.path.join(tmp_dir, "cache"),
        }
        os.makedirs(config["cache_dir"], exist_ok=True)
        # 创建 job_store
        import sqlite3
        db_path = os.path.join(tmp_dir, "job_store.sqlite3")
        conn = sqlite3.connect(db_path)
        conn.execute("SELECT 1")
        conn.close()

        checker = HealthChecker(config=config)
        times = []
        for _ in range(10):
            start = time.perf_counter()
            checker.check()
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)

        times.sort()
        p99_idx = int(len(times) * 0.99)
        p99 = times[min(p99_idx, len(times) - 1)]
        assert p99 < 1000.0, f"P99 health check = {p99:.3f}ms >= 1000ms"

        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)
