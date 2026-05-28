"""服务指标收集器（Prometheus 风格）。

支持 gauge/counter/histogram 三种指标类型，提供 Prometheus
格式导出。
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MetricSnapshot:
    """指标快照。"""
    gauges: dict[str, float]
    counters: dict[str, int]
    histograms: dict[str, dict[str, Any]]


class ServiceMetricsCollector:
    """服务级指标收集器。

    支持的预定义指标：
    - jobs_created (counter)
    - jobs_completed (counter, 按 status 标签)
    - jobs_failed (counter)
    - jobs_queued (gauge)
    - jobs_running (gauge)
    - queue_length (gauge)
    - worker_count (gauge)
    - job_duration_seconds (histogram)
    - cache_hits_total (counter)
    - cache_misses_total (counter)
    - errors_{type} (counter, 按错误类型)
    """

    def __init__(self):
        self._gauges: dict[str, float] = {}
        self._counters: dict[str, int] = defaultdict(int)
        self._histograms: dict[str, list[float]] = defaultdict(list)
        self._histogram_buckets: dict[str, list[float]] = {
            "job_duration_seconds": [0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 300.0],
            "http_request_duration_seconds": [0.01, 0.05, 0.1, 0.5, 1.0, 5.0],
        }

    # ---- Gauge ----

    def set_gauge(self, name: str, value: float) -> None:
        """设置仪表值。"""
        self._gauges[name] = value

    def get_gauge(self, name: str) -> float | None:
        return self._gauges.get(name)

    # ---- Counter ----

    def increment(self, name: str, value: int = 1) -> None:
        """计数器递增。"""
        self._counters[name] += value

    def get_counter(self, name: str) -> int:
        return self._counters.get(name, 0)

    # ---- Histogram ----

    def observe(self, name: str, value: float) -> None:
        """记录观测值到直方图。"""
        self._histograms[name].append(value)

    def get_histogram(self, name: str) -> dict[str, Any]:
        values = self._histograms.get(name, [])
        if not values:
            return {"count": 0, "sum": 0, "avg": 0, "min": 0, "max": 0}

        # 计算 bucket 分布
        buckets = self._histogram_buckets.get(name, [])
        bucket_counts = self._compute_buckets(values, buckets)

        return {
            "count": len(values),
            "sum": sum(values),
            "avg": sum(values) / len(values),
            "min": min(values),
            "max": max(values),
            "buckets": bucket_counts,
        }

    @staticmethod
    def _compute_buckets(values: list[float], boundaries: list[float]) -> list[tuple[str, int]]:
        """计算直方图 bucket 计数。"""
        sorted_bounds = sorted(boundaries)
        result = []
        for bound in sorted_bounds:
            count = sum(1 for v in values if v <= bound)
            result.append((f"le={bound}", count))
        # +Inf bucket
        result.append(("le=+Inf", len(values)))
        return result

    # ---- 预定义指标 ----

    def record_job_created(self) -> None:
        self.increment("jobs_created")

    def record_job_completed(self, status: str = "success") -> None:
        """记录任务完成，status 为 success/failed/cancelled。"""
        self.increment(f"jobs_completed_{status}")
        # 总体计数器
        self.increment("jobs_completed_total")

    def record_job_failed(self) -> None:
        """记录任务失败（便捷方法）。"""
        self.increment("jobs_failed")

    def record_job_duration(self, seconds: float) -> None:
        self.observe("job_duration_seconds", seconds)

    def set_queue_length(self, length: int) -> None:
        """设置队列长度。"""
        self.set_gauge("queue_length", float(length))

    def set_worker_count(self, count: int) -> None:
        """设置活跃 Worker 数量。"""
        self.set_gauge("worker_count", float(count))

    def set_jobs_queued(self, count: int) -> None:
        """设置排队任务数。"""
        self.set_gauge("jobs_queued", float(count))

    def set_jobs_running(self, count: int) -> None:
        """设置运行中任务数。"""
        self.set_gauge("jobs_running", float(count))

    def record_cache_hit(self) -> None:
        self.increment("cache_hits_total")

    def record_cache_miss(self) -> None:
        self.increment("cache_misses_total")

    def record_request_duration(self, seconds: float) -> None:
        self.observe("http_request_duration_seconds", seconds)

    def record_error(self, error_type: str = "unknown") -> None:
        self.increment(f"errors_{error_type}")

    # ---- 快照 ----

    def snapshot(self) -> MetricSnapshot:
        return MetricSnapshot(
            gauges=dict(self._gauges),
            counters=dict(self._counters),
            histograms={k: self.get_histogram(k) for k in self._histograms},
        )

    # ---- Prometheus 格式输出 ----

    def to_prometheus(self) -> str:
        """生成 Prometheus 格式的指标文本。"""
        lines = []

        # Gauges
        for name, value in self._gauges.items():
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{name} {value}")

        # Counters
        for name, value in self._counters.items():
            lines.append(f"# TYPE {name} counter")
            lines.append(f"{name} {value}")

        # Histograms
        for name in self._histograms:
            hist = self.get_histogram(name)
            lines.append(f"# TYPE {name} histogram")
            lines.append(f"{name}_count {hist['count']}")
            lines.append(f"{name}_sum {hist['sum']}")

            # Bucket lines
            if "buckets" in hist:
                cumulative = 0
                for label, count in hist["buckets"]:
                    cumulative = count  # Prometheus 使用累积计数
                    lines.append(f'{name}_bucket{{{label}}} {cumulative}')

        return "\n".join(lines)
