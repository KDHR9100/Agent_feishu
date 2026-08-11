"""
后台任务模块 (s13)

设计:
- 慢操作可丢到后台线程执行, 不阻塞主对话
- run_in_background 参数: 调用方显式请求
- 后台完成后通过回调推送结果 (飞书消息)
- 任务注册表: 跟踪运行中的后台任务

解耦设计:
- 不依赖 workflow 主链路, 通过 run_background 函数接口调用
- 完成回调由调用方传入 (通常是 feishu_tool.send_message)
"""
import logging
import threading
import uuid
from typing import Callable, Dict, Optional
from datetime import datetime

logger = logging.getLogger("background_tasks")

# 后台任务注册表 (内存)
_tasks: Dict[str, dict] = {}
_lock = threading.Lock()


def run_background(
    func: Callable,
    args: tuple = (),
    kwargs: dict = None,
    on_complete: Optional[Callable] = None,
    conversation_id: str = "",
    description: str = "",
) -> str:
    """
    在后台线程执行慢操作

    Args:
        func: 要执行的函数
        args: 位置参数
        kwargs: 关键字参数
        on_complete: 完成回调, 接收 (task_id, result, error)
        conversation_id: 会话 ID (用于推送通知)
        description: 任务描述

    Returns:
        task_id
    """
    kwargs = kwargs or {}
    task_id = str(uuid.uuid4())[:12]

    with _lock:
        _tasks[task_id] = {
            "task_id": task_id,
            "conversation_id": conversation_id,
            "description": description,
            "status": "running",
            "started_at": datetime.now().isoformat(),
            "result": None,
            "error": None,
        }

    def _worker():
        try:
            result = func(*args, **kwargs)
            with _lock:
                _tasks[task_id]["status"] = "completed"
                _tasks[task_id]["result"] = result
            logger.info("[bg_task] %s completed: %s", task_id, description)
            if on_complete:
                try:
                    on_complete(task_id, result, None)
                except Exception as cb_err:
                    logger.error("[bg_task] %s on_complete error: %s", task_id, cb_err)
        except Exception as e:
            with _lock:
                _tasks[task_id]["status"] = "failed"
                _tasks[task_id]["error"] = str(e)
            logger.error("[bg_task] %s failed: %s", task_id, e, exc_info=True)
            if on_complete:
                try:
                    on_complete(task_id, None, str(e))
                except Exception as cb_err:
                    logger.error("[bg_task] %s on_complete error: %s", task_id, cb_err)

    t = threading.Thread(target=_worker, daemon=True, name="bg-%s" % task_id[:8])
    t.start()
    logger.info("[bg_task] %s started: %s", task_id, description)
    return task_id


def get_task_status(task_id: str) -> Optional[dict]:
    """查询后台任务状态"""
    with _lock:
        return _tasks.get(task_id)


def list_running_tasks() -> list:
    """列出运行中的后台任务"""
    with _lock:
        return [t for t in _tasks.values() if t["status"] == "running"]


def cleanup_completed(max_keep: int = 100):
    """清理已完成的任务记录 (防止内存泄漏)"""
    with _lock:
        completed = [tid for tid, t in _tasks.items() if t["status"] in ("completed", "failed")]
        if len(completed) > max_keep:
            for tid in completed[:len(completed) - max_keep]:
                del _tasks[tid]
            logger.info("[bg_task] cleaned %d completed tasks", len(completed) - max_keep)


def default_complete_callback(conversation_id: str):
    """创建默认完成回调 (推送飞书消息)"""
    def _cb(task_id, result, error):
        try:
            from app.tools.feishu_tool import feishu_tool
            if error:
                msg = "后台任务执行失败: %s" % str(error)[:200]
            else:
                text = str(result)[:2000] if result else "完成"
                msg = "后台任务已完成:\n\n%s" % text
            feishu_tool.send_message(conversation_id, msg)
        except Exception as e:
            logger.error("[bg_task] send notification failed: %s", e)
    return _cb
