# -*- coding: utf-8 -*-
"""每用户滑动窗口限流器: 生产环境流量防护

- /chat 与飞书消息入口共用; 超限返回 429 / 友好提示
- 窗口大小与阈值按 (key, 时间戳队列) 滑动统计, 线程安全
- RATE_LIMIT_PER_MINUTE 环境变量控制阈值 (默认 30 次/分钟)
"""
import os
import threading
import time
from collections import defaultdict, deque


def _get_limit():
    return int(os.getenv("RATE_LIMIT_PER_MINUTE", "30"))


class RateLimiter:
    def __init__(self, max_requests=None, window_seconds=60):
        self.max_requests = max_requests if max_requests is not None else _get_limit()
        self.window_seconds = window_seconds
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key):
        """尝试消费一次配额: 窗口内未超限返回 True 并记录, 否则 False"""
        now = time.time()
        cutoff = now - self.window_seconds
        with self._lock:
            dq = self._hits[key]
            while dq and dq[0] <= cutoff:
                dq.popleft()
            if len(dq) >= self.max_requests:
                return False
            dq.append(now)
            return True

    def remaining(self, key):
        """查询 key 在当前窗口内的剩余配额"""
        now = time.time()
        cutoff = now - self.window_seconds
        with self._lock:
            dq = self._hits.get(key)
            if not dq:
                return self.max_requests
            return max(0, self.max_requests - sum(1 for t in dq if t > cutoff))

    def reset(self, key=None):
        """清空限流记录 (key=None 时清空全部, 供测试使用)"""
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)


# 全局单例
rate_limiter = RateLimiter()