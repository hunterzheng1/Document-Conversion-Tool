"""observability 集成测试：验证健康检查、指标、脱敏协同工作。"""

import os
import sys
import tempfile
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from docconv.infra.health_check import HealthChecker
from docconv.infra.service_metrics import ServiceMetricsCollector
from docconv.infra.redaction import redact_text, redact_dict
from docconv.infra.logger import setup_logger, _RedactingFormatter
from docconv.output.report_writer import ReportWriter
from docconv.core.types import ConversionResult, PageContent


class TestObservabilityIntegration:
    """测试 observability 各模块协同工作。"""

    def test_health_with_workers_and_metrics(self, tmp_path):
        """健康检查 + Worker 心跳 + 指标协同。"""
        # 创建存储目录
        storage = str(tmp_path)
        os.makedirs(tmp_path / "cache", exist_ok=True)

        import sqlite3
        db_path = str(tmp_path / "job_store.sqlite3")
        conn = sqlite3.connect(db_path)
        conn.execute("SELECT 1")
        conn.close()

        config = {
            "storage_root": storage,
            "cache_dir": str(tmp_path / "cache"),
            "worker_stale_seconds": 5,
        }

        health = HealthChecker(config=config)
        metrics = ServiceMetricsCollector()

        # 模拟 Worker 上线
        health.record_heartbeat("w1", "job_001")
        health.record_heartbeat("w2", None)

        # 模拟任务执行
        metrics.record_job_created()
        metrics.record_job_completed("success")
        metrics.record_job_duration(3.5)
        metrics.set_worker_count(health.get_active_worker_count())
        metrics.set_queue_length(0)

        # 健康检查
        result = health.check()
        assert result.overall in ("ok", "degraded")

        # 验证 Worker 被识别
        worker_comp = next(c for c in result.components if c.name == "worker")
        assert worker_comp.status == "ok"
        assert "2 个 Worker" in worker_comp.message

        # 验证指标
        assert metrics.get_gauge("worker_count") == 2.0
        assert metrics.get_counter("jobs_created") == 1
        assert metrics.get_counter("jobs_completed_total") == 1

    def test_redacted_log_in_health_message(self):
        """健康检查消息不应包含敏感信息。"""
        checker = HealthChecker()
        # 即使手动注入敏感信息到心跳数据
        checker.record_heartbeat("w1", "job_with_key_sk-ant-abcdef1234567890abcdef12")

        result = checker.check()
        worker_comp = next(c for c in result.components if c.name == "worker")

        # 脱敏处理消息
        safe_msg = redact_text(worker_comp.message)
        assert "sk-ant-" not in safe_msg

    def test_full_pipeline_with_redacted_errors(self, tmp_path):
        """完整转换流程：错误脱敏 + 指标记录 + 报告生成。"""
        metrics = ServiceMetricsCollector()
        writer = ReportWriter()

        # 模拟失败任务
        metrics.record_job_created()
        metrics.record_error("APIError")
        metrics.record_job_duration(1.2)

        # 包含 API Key 的错误消息
        error_msg = "API call failed with key sk-ant-abc1234567890abcdef1234567890ab"
        safe_error = redact_text(error_msg)
        assert "sk-ant-" not in safe_error
        assert "***REDACTED***" in safe_error

        # 创建转换结果
        result = ConversionResult(
            file_path="test.pdf",
            total_pages=1,
            pages=[
                PageContent(
                    page_num=1,
                    page_type="text_only",
                    markdown="content",
                    errors=[safe_error],
                ),
            ],
            errors=[safe_error],
        )

        # 生成带指标的报告
        output = str(tmp_path / "integration_report.md")
        path = writer.write_report_with_metrics(result, output, metrics=metrics)

        content = open(path, encoding="utf-8").read()
        assert "服务指标摘要" in content
        assert "errors_APIError" in content or "APIError" in content

    def test_worker_stale_triggers_degraded_and_metrics_update(self):
        """Worker 心跳超时触发降级 + 指标更新。"""
        config = {"worker_stale_seconds": 1}
        health = HealthChecker(config=config)
        metrics = ServiceMetricsCollector()

        health.record_heartbeat("w1")

        # 模拟心跳过期
        health._worker_heartbeats["w1"].last_seen = time.time() - 10

        result = health.check()
        assert result.overall == "degraded"

        # 更新指标
        metrics.set_worker_count(health.get_active_worker_count())
        assert metrics.get_gauge("worker_count") == 0.0

    def test_prometheus_output_includes_service_metrics(self):
        """Prometheus 输出应包含全部服务指标。"""
        metrics = ServiceMetricsCollector()

        # 设置全部指标
        metrics.set_queue_length(5)
        metrics.set_worker_count(3)
        metrics.set_jobs_queued(5)
        metrics.set_jobs_running(2)
        metrics.record_job_created()
        metrics.record_job_completed("success")
        metrics.record_job_failed()
        metrics.record_cache_hit()
        metrics.record_cache_miss()
        metrics.record_error("timeout")
        metrics.record_job_duration(10.0)

        output = metrics.to_prometheus()

        # 验证全部指标存在
        assert "queue_length" in output
        assert "worker_count" in output
        assert "jobs_queued" in output
        assert "jobs_running" in output
        assert "jobs_created" in output
        assert "jobs_completed_total" in output
        assert "jobs_failed" in output
        assert "cache_hits_total" in output
        assert "cache_misses_total" in output
        assert "errors_timeout" in output
        assert "job_duration_seconds_count" in output
        assert "job_duration_seconds_sum" in output

    def test_logger_redaction_preserves_job_id(self, capsys):
        """日志脱敏不应影响 job_id 等普通标识符。"""
        import logging

        logger = logging.getLogger("test_integration_redact")
        logger.handlers.clear()
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_RedactingFormatter(fmt="%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        logger.info("job_abc_001 started by user admin")
        captured = capsys.readouterr()
        assert "job_abc_001" in captured.out
        assert "admin" in captured.out

    def test_redact_dict_preserves_structure(self):
        """字典脱敏应保持结构完整。"""
        data = {
            "job_id": "job_001",
            "api_key": "sk-ant-abc123",
            "status": "running",
            "config": {
                "token": "secret_token_value",
                "timeout": 30,
            },
        }

        result = redact_dict(data)
        assert result["job_id"] == "job_001"
        assert result["api_key"] == "***REDACTED***"
        assert result["status"] == "running"
        assert result["config"]["token"] == "***REDACTED***"
        assert result["config"]["timeout"] == 30
