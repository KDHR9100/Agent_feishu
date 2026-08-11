"""
Hook 扩展点模块 (s04)

设计:
- 四个生命周期事件点: UserPromptSubmit / PreToolUse / PostToolUse / Stop
- hook 注册表: register_hook(event, handler) 注册
- trigger_hooks(event, context) 触发: 按注册顺序执行所有 handler
- handler 可以修改 context (返回 dict 合并)
- 权限检查、日志等横切关注点挂在 hook 上, 不写死在主循环

解耦设计:
- hook handler 通过 register_hook 注册, 不侵入主链路代码
- context 是可变 dict, handler 可以读取和修改
- handler 异常不影响主流程 (catch and log)
"""
import logging
from typing import Callable, Dict, List, Any

logger = logging.getLogger("hooks")

# 事件类型
EVENTS = ("UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")

# 注册表: {event: [handler, ...]}
_registry: Dict[str, List[Callable]] = {e: [] for e in EVENTS}


def register_hook(event: str, handler: Callable):
    """注册 hook handler

    Args:
        event: 事件名 (UserPromptSubmit / PreToolUse / PostToolUse / Stop)
        handler: 可调用对象, 接收 context dict, 返回可选 dict (合并到 context)
    """
    if event not in EVENTS:
        logger.warning("[hooks] unknown event: %s", event)
        return
    _registry[event].append(handler)
    logger.info("[hooks] registered %s -> %s", event, getattr(handler, "__name__", str(handler)))


def unregister_hook(event: str, handler: Callable):
    """取消注册"""
    if event in _registry and handler in _registry[event]:
        _registry[event].remove(handler)
        logger.info("[hooks] unregistered %s -> %s", event, getattr(handler, "__name__", str(handler)))


def trigger_hooks(event: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """触发事件的所有 hook, 返回可能被修改的 context

    Args:
        event: 事件名
        context: 上下文 dict

    Returns:
        可能被 handler 修改后的 context
    """
    if event not in _registry:
        return context

    for handler in _registry[event]:
        try:
            result = handler(context)
            if isinstance(result, dict):
                context.update(result)
        except Exception as e:
            logger.error(
                "[hooks] %s handler %s error: %s",
                event, getattr(handler, "__name__", str(handler)), e,
            )
            # hook 异常不影响主流程

    return context


def clear_hooks(event: str = None):
    """清除 hook (用于测试)"""
    if event:
        _registry[event] = []
    else:
        for e in EVENTS:
            _registry[e] = []


def list_hooks(event: str = None) -> Dict[str, List[str]]:
    """列出已注册的 hook (用于调试)"""
    if event:
        return {event: [getattr(h, "__name__", str(h)) for h in _registry.get(event, [])]}
    return {e: [getattr(h, "__name__", str(h)) for h in hs] for e, hs in _registry.items()}
