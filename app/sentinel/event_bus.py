"""L4 内存事件总线 (旁路架构的新旧系统通信枢纽)

设计要点:
- 线程安全的进程内 pub/sub, API 与 Redis Pub/Sub 语义对齐, 后续可无缝替换为 Redis
- 哨兵层发布 MARKET_ALERT / INVENTORY_LOW, 决策层与执行层按需订阅
- 保留最近事件历史, 便于审计与测试断言
"""
import logging
import threading
import time
from collections import defaultdict

logger = logging.getLogger("sentinel.event_bus")

# ===== 预定义事件类型 =====
MARKET_ALERT = "MARKET_ALERT"      # 竞品价格波动/差评突增
INVENTORY_LOW = "INVENTORY_LOW"    # 库存不足预警


class EventBus:
    """简单的内存事件总线 (publish/subscribe)"""

    def __init__(self, max_history=200):
        self._subscribers = defaultdict(list)
        self._lock = threading.Lock()
        self._history = []
        self._max_history = max_history

    def subscribe(self, event_type, handler):
        """订阅事件; handler 签名: handler(event: dict) -> None"""
        with self._lock:
            if handler not in self._subscribers[event_type]:
                self._subscribers[event_type].append(handler)
        logger.debug("[event_bus] subscribed %s -> %s", event_type, getattr(handler, "__name__", handler))

    def unsubscribe(self, event_type, handler):
        with self._lock:
            if handler in self._subscribers[event_type]:
                self._subscribers[event_type].remove(handler)

    def publish(self, event_type, data=None):
        """发布事件, 同步派发给所有订阅者 (单个订阅者异常不影响其他订阅者)

        Returns:
            int: 成功派发的订阅者数量
        """
        event = {
            "type": event_type,
            "data": data or {},
            "timestamp": time.time(),
        }
        with self._lock:
            handlers = list(self._subscribers.get(event_type, []))
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

        logger.info(
            "[event_bus] publish %s | subscribers=%d | keys=%s",
            event_type, len(handlers), list((data or {}).keys()),
        )
        delivered = 0
        for handler in handlers:
            try:
                handler(event)
                delivered += 1
            except Exception as e:
                logger.error(
                    "[event_bus] handler error on %s: %s", event_type, e, exc_info=True
                )
        return delivered

    def get_history(self, event_type=None):
        """查询事件历史 (可按类型过滤), 返回副本"""
        with self._lock:
            if event_type is None:
                return list(self._history)
            return [e for e in self._history if e["type"] == event_type]

    def clear(self):
        """清空订阅与历史 (仅供测试使用)"""
        with self._lock:
            self._subscribers.clear()
            self._history.clear()


# 全局单例
event_bus = EventBus()
