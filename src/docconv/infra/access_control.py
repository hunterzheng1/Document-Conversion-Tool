"""来源访问控制与速率限制器。

提供统一的 allowlist 校验和滑动窗口速率限制。
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AllowlistResult:
    """allowlist 校验结果。"""
    allowed: bool
    reason: str = ""


@dataclass
class RateLimitResult:
    """速率限制结果。"""
    allowed: bool
    remaining: int = 0
    retry_after_seconds: float = 0
    reason: str = ""


class AllowlistChecker:
    """来源 allowlist 校验器。

    支持按 chat_id、tenant、user 的白名单校验。
    """

    def __init__(self, allowed_ids: set[str] | None = None):
        self._allowed = allowed_ids or set()

    def add_allowed(self, id_or_ids: str | list[str]) -> None:
        """添加允许的 ID。"""
        if isinstance(id_or_ids, str):
            self._allowed.add(id_or_ids)
        else:
            self._allowed.update(id_or_ids)

    def remove_allowed(self, id_: str) -> None:
        """移除允许的 ID。"""
        self._allowed.discard(id_)

    def check(self, source_id: str) -> AllowlistResult:
        """校验来源是否在 allowlist 中。

        Args:
            source_id: 来源标识（chat_id、tenant 等）

        Returns:
            AllowlistResult
        """
        if not self._allowed:
            # 空 allowlist 默认全部允许
            return AllowlistResult(allowed=True)

        if source_id in self._allowed:
            return AllowlistResult(allowed=True)

        return AllowlistResult(
            allowed=False,
            reason=f"来源 {source_id} 不在 allowlist 中",
        )


class SlidingWindowRateLimiter:
    """滑动窗口速率限制器。

    按来源独立计数，窗口为滑动窗口。
    """

    def __init__(self, max_requests_per_minute: int = 5):
        self.max_requests = max_requests_per_minute
        # source_id -> [timestamp, ...]
        self._requests: dict[str, list[float]] = defaultdict(list)

    def check(self, source_id: str) -> RateLimitResult:
        """检查来源是否超出速率限制。

        Args:
            source_id: 来源标识

        Returns:
            RateLimitResult
        """
        now = time.time()
        window_start = now - 60.0

        # 清理过期记录
        timestamps = self._requests[source_id]
        self._requests[source_id] = [t for t in timestamps if t > window_start]

        current_count = len(self._requests[source_id])

        if current_count >= self.max_requests:
            # 计算最早的请求何时过期
            oldest = min(self._requests[source_id]) if self._requests[source_id] else now
            retry_after = oldest + 60.0 - now
            return RateLimitResult(
                allowed=False,
                retry_after_seconds=max(0, retry_after),
                reason=f"超出速率限制（{self.max_requests} jobs/分钟）",
            )

        # 记录请求
        self._requests[source_id].append(now)
        return RateLimitResult(
            allowed=True,
            remaining=self.max_requests - current_count - 1,
        )


class AccessControlMiddleware:
    """统一访问控制中间件。

    组合 allowlist 和速率限制。
    """

    def __init__(
        self,
        allowed_ids: set[str] | None = None,
        max_jobs_per_minute: int = 5,
    ):
        self.allowlist = AllowlistChecker(allowed_ids)
        self.rate_limiter = SlidingWindowRateLimiter(max_jobs_per_minute)

    def check_access(self, source_id: str) -> AllowlistResult | RateLimitResult:
        """检查访问权限。

        先检查 allowlist，再检查速率限制。

        Args:
            source_id: 来源标识

        Returns:
            如果 allowlist 拒绝返回 AllowlistResult，
            如果速率限制返回 RateLimitResult，
            如果通过返回 allowed=True 的 RateLimitResult
        """
        # 1. allowlist 检查
        allow_result = self.allowlist.check(source_id)
        if not allow_result.allowed:
            return allow_result

        # 2. 速率限制检查
        rate_result = self.rate_limiter.check(source_id)
        if not rate_result.allowed:
            return rate_result

        return rate_result
