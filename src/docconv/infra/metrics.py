"""指标收集器：收集转换过程的指标数据。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class ConversionMetrics:
    """转换指标。"""
    total_files: int = 0
    completed_files: int = 0
    failed_files: int = 0
    total_pages: int = 0
    total_time_seconds: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    errors: list[str] = field(default_factory=list)


class MetricsCollector:
    """收集和管理转换指标。"""

    def __init__(self):
        self._metrics = ConversionMetrics()
        self._start_time: float | None = None

    def start(self) -> None:
        self._start_time = time.time()

    def stop(self) -> None:
        if self._start_time:
            self._metrics.total_time_seconds += time.time() - self._start_time

    def record_file_completed(self, pages: int = 0) -> None:
        self._metrics.total_files += 1
        self._metrics.completed_files += 1
        self._metrics.total_pages += pages

    def record_file_failed(self) -> None:
        self._metrics.total_files += 1
        self._metrics.failed_files += 1

    def record_token_usage(self, input_tokens: int, output_tokens: int) -> None:
        self._metrics.total_input_tokens += input_tokens
        self._metrics.total_output_tokens += output_tokens

    def record_error(self, error: str) -> None:
        self._metrics.errors.append(error)

    def get_metrics(self) -> ConversionMetrics:
        return self._metrics

    def summary(self) -> str:
        m = self._metrics
        return (
            f"转换完成: {m.completed_files}/{m.total_files} 文件, "
            f"{m.total_pages} 页, "
            f"{m.total_time_seconds:.1f}s, "
            f"Token: {m.total_input_tokens}/{m.total_output_tokens} (in/out)"
        )
