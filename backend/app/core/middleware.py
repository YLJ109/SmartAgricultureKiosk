"""中间件：请求日志 + 滑动窗口限流。

限流是进程内实现（一把锁 + 字典），适合单实例部署。
多实例部署时应换成 Redis，否则各实例各限各的，等于没限。
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware

# 需要限流的路径前缀 -> (窗口秒数, 窗口内最大请求数)
RATE_RULES: dict[str, tuple[int, int]] = {
    "/api/recognize": (60, 30),   # 识别比较重，每分钟 30 次
    "/api/chat": (60, 40),
    "/api/auth/login": (300, 20),  # 登录用于防爆破
}

_SKIP_LOG_PATHS = {"/api/system/health", "/favicon.ico", "/docs", "/openapi.json"}


class RequestLogMiddleware(BaseHTTPMiddleware):
    """记录每个请求的方法、路径、状态码、耗时。慢请求单独标出来。"""

    async def dispatch(self, request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        cost_ms = (time.perf_counter() - started) * 1000

        if request.url.path not in _SKIP_LOG_PATHS:
            level = "WARNING" if cost_ms > 3000 else "INFO"
            logger.log(
                level,
                "{method} {path} -> {status} {cost:.0f}ms",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                cost=cost_ms,
            )
        response.headers["X-Process-Time-Ms"] = f"{cost_ms:.0f}"
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """按 IP + 路径前缀做滑动窗口限流。被限流时返回 429。"""

    def __init__(self, app) -> None:
        super().__init__(app)
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _rule_for(self, path: str) -> tuple[str, int, int] | None:
        for prefix, (window, limit) in RATE_RULES.items():
            if path.startswith(prefix):
                return prefix, window, limit
        return None

    async def dispatch(self, request: Request, call_next):
        rule = self._rule_for(request.url.path)
        if rule is None:
            return await call_next(request)

        prefix, window, limit = rule
        client_ip = request.client.host if request.client else "unknown"
        key = f"{client_ip}:{prefix}"
        now = time.time()

        bucket = self._hits[key]
        while bucket and now - bucket[0] > window:
            bucket.popleft()

        if len(bucket) >= limit:
            retry_after = int(window - (now - bucket[0])) + 1
            logger.warning("限流触发：{} {}（{} 秒内已 {} 次）", client_ip, request.url.path, window, len(bucket))
            return JSONResponse(
                status_code=429,
                content={
                    "code": "rate_limited",
                    "message": f"操作过于频繁，请 {retry_after} 秒后再试",
                    "detail": {"retry_after": retry_after},
                },
                headers={"Retry-After": str(retry_after)},
            )

        bucket.append(now)
        return await call_next(request)
