"""BI-12: 来源访问控制与速率限制测试。"""

import time
from unittest.mock import patch

from docconv.infra.access_control import (
    AllowlistChecker,
    SlidingWindowRateLimiter,
    AccessControlMiddleware,
)


class TestAllowlistChecker:
    """Allowlist 校验器测试。"""

    def test_empty_allows_all(self):
        checker = AllowlistChecker()
        result = checker.check("any_chat_id")
        assert result.allowed is True

    def test_allowed_chat(self):
        checker = AllowlistChecker(allowed_ids={"chat_1", "chat_2"})
        result = checker.check("chat_1")
        assert result.allowed is True

    def test_denied_chat(self):
        checker = AllowlistChecker(allowed_ids={"chat_1"})
        result = checker.check("chat_999")
        assert result.allowed is False
        assert "不在 allowlist" in result.reason

    def test_add_allowed(self):
        checker = AllowlistChecker(allowed_ids={"chat_1"})
        checker.add_allowed("chat_2")
        assert checker.check("chat_2").allowed is True

    def test_remove_allowed(self):
        checker = AllowlistChecker(allowed_ids={"chat_1", "chat_2"})
        checker.remove_allowed("chat_1")
        assert checker.check("chat_1").allowed is False

    def test_remove_nonexistent(self):
        checker = AllowlistChecker(allowed_ids={"chat_1"})
        checker.remove_allowed("chat_999")  # 不应抛异常
        assert checker.check("chat_1").allowed is True


class TestSlidingWindowRateLimiter:
    """滑动窗口速率限制器测试。"""

    def test_within_limit(self):
        limiter = SlidingWindowRateLimiter(max_requests_per_minute=3)
        for i in range(3):
            result = limiter.check("source_1")
            assert result.allowed is True

    def test_exceed_limit(self):
        limiter = SlidingWindowRateLimiter(max_requests_per_minute=2)
        limiter.check("source_1")
        limiter.check("source_1")
        result = limiter.check("source_1")
        assert result.allowed is False
        assert "超出速率" in result.reason

    def test_independent_counters(self):
        """不同来源应独立计数。"""
        limiter = SlidingWindowRateLimiter(max_requests_per_minute=1)
        limiter.check("source_a")
        # source_a 应被限流
        assert limiter.check("source_a").allowed is False
        # source_b 应仍可用
        assert limiter.check("source_b").allowed is True

    def test_remaining_count(self):
        limiter = SlidingWindowRateLimiter(max_requests_per_minute=5)
        result1 = limiter.check("source_1")
        assert result1.remaining == 4
        result2 = limiter.check("source_1")
        assert result2.remaining == 3

    def test_window_expiry(self):
        """请求记录应随窗口过期而清除。"""
        limiter = SlidingWindowRateLimiter(max_requests_per_minute=1)
        limiter.check("source_1")
        assert limiter.check("source_1").allowed is False

        # 模拟时间前进 61 秒
        with patch("docconv.infra.access_control.time.time", return_value=time.time() + 61):
            result = limiter.check("source_1")
            assert result.allowed is True


class TestAccessControlMiddleware:
    """统一访问控制中间件测试。"""

    def test_allowlist_reject(self):
        middleware = AccessControlMiddleware(
            allowed_ids={"chat_1"},
            max_jobs_per_minute=5,
        )
        result = middleware.check_access("chat_999")
        assert result.allowed is False
        assert "allowlist" in result.reason.lower() or "不在" in result.reason

    def test_rate_limit_reject(self):
        middleware = AccessControlMiddleware(
            max_jobs_per_minute=1,
        )
        middleware.check_access("chat_1")
        result = middleware.check_access("chat_1")
        assert result.allowed is False

    def test_both_pass(self):
        middleware = AccessControlMiddleware(
            allowed_ids={"chat_1"},
            max_jobs_per_minute=5,
        )
        result = middleware.check_access("chat_1")
        assert result.allowed is True

    def test_empty_allowlist_passes(self):
        """空 allowlist 应全部允许。"""
        middleware = AccessControlMiddleware(
            max_jobs_per_minute=5,
        )
        result = middleware.check_access("any_chat")
        assert result.allowed is True
