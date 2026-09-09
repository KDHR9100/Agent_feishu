"""Trajectory 数据模型与 JSONL 读写。

一行 JSONL = 一个 episode（与方案文档 §3.2 契约一致）：
run_id / persona_id / goal / mode / turns[] / termination / scores。

所有结构均为 JSON 可序列化的普通 dict，评测器接口以 dict 为准，
避免评测层与 Pydantic 模型强耦合。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional

#: 单字段落盘截断上限（防止真实模式 skill_results 撑爆 JSONL）
MAX_FIELD_LEN = 2000


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def truncate(text: object, limit: int = MAX_FIELD_LEN) -> str:
    """任意值转字符串并截断，保住证据又不撑爆产物。"""

    s = text if isinstance(text, str) else str(text)
    if len(s) <= limit:
        return s
    return s[: limit - 15] + "...(truncated)"


def new_trajectory(
    run_id: str,
    persona_id: str,
    persona_name: str,
    goal: str,
    mode: str,
) -> Dict[str, object]:
    """创建一个 episode 的 trajectory 骨架。"""

    return {
        "run_id": run_id,
        "persona_id": persona_id,
        "persona_name": persona_name,
        "goal": goal,
        "mode": mode,
        "started_at": _now_iso(),
        "finished_at": None,
        "turns": [],
        "termination": {"reason": None, "turns_used": 0},
        "scores": {},
        "error": None,
    }


def make_turn_record(
    turn: int,
    user_message: str,
    agent_answer: str,
    intent: str,
    skills_to_execute: Optional[List[str]] = None,
    skill_results: Optional[List[Dict[str, object]]] = None,
    execution_plan: Optional[List[Dict[str, object]]] = None,
    reflect_decision: str = "sufficient",
    retry_rounds: int = 0,
    token_usage: Optional[Dict[str, int]] = None,
    node_timings_ms: Optional[Dict[str, float]] = None,
    safety_events: Optional[List[Dict[str, object]]] = None,
) -> Dict[str, object]:
    """构造单轮记录（与方案 §3.2 TurnRecord 字段一一对应）。"""

    return {
        "turn": turn,
        "user_message": truncate(user_message),
        "agent_answer": truncate(agent_answer),
        "intent": intent,
        "skills_to_execute": list(skills_to_execute or []),
        "skill_results": [
            {
                "skill": sr.get("skill", "unknown"),
                "type": sr.get("type", ""),
                "data": truncate(sr.get("data", "")),
            }
            for sr in (skill_results or [])
        ],
        "execution_plan": execution_plan,
        "reflect_decision": reflect_decision,
        "retry_rounds": retry_rounds,
        "token_usage": token_usage or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "node_timings_ms": node_timings_ms or {},
        "safety_events": safety_events or [],
    }


def finish_trajectory(traj: Dict[str, object], reason: str) -> Dict[str, object]:
    """标记 episode 终止。"""

    traj["termination"] = {
        "reason": reason,
        "turns_used": len(traj.get("turns", [])),  # type: ignore[arg-type]
    }
    traj["finished_at"] = _now_iso()
    return traj


class TrajectoryWriter:
    """JSONL 追加写入器：崩溃也保留已完成 episode。"""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a", encoding="utf-8")

    def write(self, episode: Dict[str, object]) -> None:
        self._fh.write(json.dumps(episode, ensure_ascii=False) + "\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()

    def __enter__(self) -> "TrajectoryWriter":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def read_jsonl(path: Path) -> Iterator[Dict[str, object]]:
    """读取 JSONL 文件为 dict 迭代器（跳过空行/坏行并记 warning）。"""

    import structlog

    log = structlog.get_logger(__name__)
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                log.warning("skip_bad_jsonl_line", file=str(path), lineno=lineno)
