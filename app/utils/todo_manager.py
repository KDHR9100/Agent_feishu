"""
Todo 任务管理模块 (s05)

设计:
- 维护 pending/in_progress/completed 状态列表
- 进度展示: 返回 todo 列表供 answer 节点展示
- 未更新提醒: 连续 N 轮未更新 todo 时注入提醒
- 状态存储在 AgentState["todo_list"] 中, 随会话生命周期

解耦设计:
- 独立于 workflow 主链路, 通过函数接口操作
- workflow 在 reflect 节点检查未更新轮数
"""
import logging
from typing import List, Dict, Optional
from datetime import datetime

logger = logging.getLogger("todo_manager")

# 连续 N 轮未更新 todo 时注入提醒
TODO_STALE_THRESHOLD = 2


def create_todo(items: List[str]) -> List[Dict]:
    """创建 todo 列表, 全部初始为 pending"""
    return [
        {
            "content": item,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
        }
        for item in items
    ]


def update_status(todo_list: List[Dict], index: int, status: str) -> List[Dict]:
    """更新指定位置的 todo 状态"""
    if not todo_list or index < 0 or index >= len(todo_list):
        return todo_list
    if status not in ("pending", "in_progress", "completed"):
        return todo_list
    # 同一时间只允许一个 in_progress
    if status == "in_progress":
        for t in todo_list:
            if t["status"] == "in_progress":
                t["status"] = "completed"  # 自动完成上一个
    todo_list[index]["status"] = status
    todo_list[index]["updated_at"] = datetime.now().isoformat()
    return todo_list


def next_pending(todo_list: List[Dict]) -> Optional[int]:
    """返回第一个 pending 的索引, 没有则返回 None"""
    for i, t in enumerate(todo_list):
        if t["status"] == "pending":
            return i
    return None


def all_completed(todo_list: List[Dict]) -> bool:
    """是否全部完成"""
    return bool(todo_list) and all(t["status"] == "completed" for t in todo_list)


def format_progress(todo_list: Optional[List[Dict]]) -> str:
    """格式化进度展示"""
    if not todo_list:
        return ""
    icons = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}
    lines = []
    for i, t in enumerate(todo_list):
        icon = icons.get(t["status"], "[?]")
        lines.append("  %d. %s %s" % (i + 1, icon, t["content"]))
    done = sum(1 for t in todo_list if t["status"] == "completed")
    total = len(todo_list)
    lines.insert(0, "进度 (%d/%d):" % (done, total))
    return "\n".join(lines)


def check_stale(state: Dict, threshold: int = TODO_STALE_THRESHOLD) -> Optional[str]:
    """
    检查是否连续 N 轮未更新 todo, 返回提醒文本或 None

    Args:
        state: AgentState, 需含 todo_list 和 todo_last_updated_round
        threshold: 连续未更新轮数阈值
    """
    todo_list = state.get("todo_list")
    if not todo_list:
        return None
    if all_completed(todo_list):
        return None
    last_updated = state.get("todo_last_updated_round", 0)
    current_round = state.get("retry_count", 0)
    # 注意: retry_count 在 reflect 节点递增, 用来近似"轮数"
    stale_rounds = current_round - last_updated
    if stale_rounds >= threshold:
        # 找到第一个未完成的
        idx = next_pending(todo_list)
        if idx is not None:
            return (
                "提醒: 任务列表已连续 %d 轮未更新, 当前待办: \"%s\"。"
                "请确认是否需要继续或调整。" % (stale_rounds, todo_list[idx]["content"])
            )
    return None


def mark_updated(state: Dict):
    """标记 todo 已更新 (重置 stale 计数)"""
    state["todo_last_updated_round"] = state.get("retry_count", 0)
