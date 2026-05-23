"""指标收集器测试。"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from docconv.infra.metrics import MetricsCollector


def test_metrics_basic():
    m = MetricsCollector()
    m.start()
    m.record_file_completed(5)
    m.record_token_usage(100, 50)
    m.record_error("test error")
    m.stop()

    metrics = m.get_metrics()
    assert metrics.completed_files == 1
    assert metrics.total_pages == 5
    assert metrics.total_input_tokens == 100
    assert metrics.total_output_tokens == 50
    assert len(metrics.errors) == 1


def test_metrics_summary():
    m = MetricsCollector()
    m.start()
    m.record_file_completed(3)
    m.stop()
    summary = m.summary()
    assert "1" in summary
