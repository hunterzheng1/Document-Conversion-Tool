"""服务指标收集器测试。"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from docconv.infra.service_metrics import ServiceMetricsCollector, MetricSnapshot


class TestGauges:
    """测试 Gauge 指标。"""

    def test_set_and_get_gauge(self):
        m = ServiceMetricsCollector()
        m.set_gauge("queue_length", 5.0)
        assert m.get_gauge("queue_length") == 5.0

    def test_get_missing_gauge_returns_none(self):
        m = ServiceMetricsCollector()
        assert m.get_gauge("nonexistent") is None

    def test_set_queue_length(self):
        m = ServiceMetricsCollector()
        m.set_queue_length(10)
        assert m.get_gauge("queue_length") == 10.0

    def test_set_worker_count(self):
        m = ServiceMetricsCollector()
        m.set_worker_count(3)
        assert m.get_gauge("worker_count") == 3.0

    def test_set_jobs_queued(self):
        m = ServiceMetricsCollector()
        m.set_jobs_queued(7)
        assert m.get_gauge("jobs_queued") == 7.0

    def test_set_jobs_running(self):
        m = ServiceMetricsCollector()
        m.set_jobs_running(2)
        assert m.get_gauge("jobs_running") == 2.0

    def test_gauge_overwrites(self):
        m = ServiceMetricsCollector()
        m.set_gauge("x", 1.0)
        m.set_gauge("x", 2.0)
        assert m.get_gauge("x") == 2.0


class TestCounters:
    """测试 Counter 指标。"""

    def test_increment_default(self):
        m = ServiceMetricsCollector()
        m.increment("test_counter")
        assert m.get_counter("test_counter") == 1

    def test_increment_custom_value(self):
        m = ServiceMetricsCollector()
        m.increment("test_counter", 5)
        assert m.get_counter("test_counter") == 5

    def test_increment_accumulates(self):
        m = ServiceMetricsCollector()
        m.increment("x")
        m.increment("x", 3)
        m.increment("x", 2)
        assert m.get_counter("x") == 6

    def test_get_missing_counter_returns_zero(self):
        m = ServiceMetricsCollector()
        assert m.get_counter("nonexistent") == 0


class TestHistograms:
    """测试 Histogram 指标。"""

    def test_observe_and_get(self):
        m = ServiceMetricsCollector()
        m.observe("latency", 1.5)
        m.observe("latency", 2.5)
        h = m.get_histogram("latency")
        assert h["count"] == 2
        assert h["sum"] == 4.0
        assert h["avg"] == 2.0
        assert h["min"] == 1.5
        assert h["max"] == 2.5

    def test_empty_histogram(self):
        m = ServiceMetricsCollector()
        h = m.get_histogram("empty")
        assert h["count"] == 0

    def test_histogram_has_buckets(self):
        m = ServiceMetricsCollector()
        m.observe("job_duration_seconds", 0.3)
        m.observe("job_duration_seconds", 5.0)
        h = m.get_histogram("job_duration_seconds")
        assert "buckets" in h
        assert len(h["buckets"]) > 0


class TestPredefinedMetrics:
    """测试预定义指标方法。"""

    def test_record_job_created(self):
        m = ServiceMetricsCollector()
        m.record_job_created()
        m.record_job_created()
        assert m.get_counter("jobs_created") == 2

    def test_record_job_completed_success(self):
        m = ServiceMetricsCollector()
        m.record_job_completed("success")
        assert m.get_counter("jobs_completed_success") == 1
        assert m.get_counter("jobs_completed_total") == 1

    def test_record_job_completed_failed(self):
        m = ServiceMetricsCollector()
        m.record_job_completed("failed")
        assert m.get_counter("jobs_completed_failed") == 1

    def test_record_job_failed(self):
        m = ServiceMetricsCollector()
        m.record_job_failed()
        m.record_job_failed()
        assert m.get_counter("jobs_failed") == 2

    def test_record_job_duration(self):
        m = ServiceMetricsCollector()
        m.record_job_duration(10.5)
        h = m.get_histogram("job_duration_seconds")
        assert h["count"] == 1
        assert h["sum"] == 10.5

    def test_record_cache_hit_miss(self):
        m = ServiceMetricsCollector()
        m.record_cache_hit()
        m.record_cache_hit()
        m.record_cache_miss()
        assert m.get_counter("cache_hits_total") == 2
        assert m.get_counter("cache_misses_total") == 1

    def test_record_error(self):
        m = ServiceMetricsCollector()
        m.record_error("timeout")
        m.record_error("timeout")
        m.record_error("internal_error")
        assert m.get_counter("errors_timeout") == 2
        assert m.get_counter("errors_internal_error") == 1


class TestSnapshot:
    """测试指标快照。"""

    def test_snapshot_contains_all_types(self):
        m = ServiceMetricsCollector()
        m.set_gauge("g", 10)
        m.increment("c", 5)
        m.observe("h", 1.0)
        snap = m.snapshot()
        assert isinstance(snap, MetricSnapshot)
        assert snap.gauges["g"] == 10
        assert snap.counters["c"] == 5
        assert snap.histograms["h"]["count"] == 1

    def test_snapshot_is_independent(self):
        m = ServiceMetricsCollector()
        m.increment("c")
        snap1 = m.snapshot()
        m.increment("c")
        snap2 = m.snapshot()
        assert snap1.counters["c"] == 1
        assert snap2.counters["c"] == 2


class TestPrometheusOutput:
    """测试 Prometheus 格式输出。"""

    def test_empty_output(self):
        m = ServiceMetricsCollector()
        output = m.to_prometheus()
        assert output == ""

    def test_gauge_output(self):
        m = ServiceMetricsCollector()
        m.set_gauge("queue_length", 5)
        output = m.to_prometheus()
        assert "# TYPE queue_length gauge" in output
        assert "queue_length 5" in output

    def test_counter_output(self):
        m = ServiceMetricsCollector()
        m.increment("jobs_created", 3)
        output = m.to_prometheus()
        assert "# TYPE jobs_created counter" in output
        assert "jobs_created 3" in output

    def test_histogram_output(self):
        m = ServiceMetricsCollector()
        m.observe("job_duration_seconds", 1.0)
        output = m.to_prometheus()
        assert "# TYPE job_duration_seconds histogram" in output
        assert "job_duration_seconds_count 1" in output
        assert "job_duration_seconds_sum 1.0" in output
        assert "job_duration_seconds_bucket{le=" in output

    def test_full_output_format(self):
        m = ServiceMetricsCollector()
        m.set_gauge("queue_length", 2)
        m.set_gauge("worker_count", 1)
        m.record_job_created()
        m.record_job_created()
        m.record_job_completed("success")
        m.record_cache_hit()
        m.record_cache_miss()
        m.record_error("timeout")
        m.record_job_duration(5.0)

        output = m.to_prometheus()
        lines = output.split("\n")

        # 验证基本结构
        type_lines = [l for l in lines if l.startswith("# TYPE")]
        assert len(type_lines) >= 6  # 至少 6 个指标类型声明
