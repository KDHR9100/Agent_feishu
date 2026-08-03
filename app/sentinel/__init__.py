"""L4 市场哨兵模块 (主动感知层)

旁路架构: 不侵入 app/agent 既有逻辑, 通过 event_bus 与决策/执行层异步通信。
"""
from .event_bus import event_bus, MARKET_ALERT, INVENTORY_LOW
from .trigger_engine import sentinel, MarketSentinel

__all__ = ["event_bus", "MARKET_ALERT", "INVENTORY_LOW", "sentinel", "MarketSentinel"]
