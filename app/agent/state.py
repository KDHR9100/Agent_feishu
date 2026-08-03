from typing import TypedDict, Optional, List, Dict


class AgentState(TypedDict, total=False):
    user_input: str
    conversation_id: Optional[str]
    history: Optional[List[Dict]]
    tool_result: Optional[dict]
    answer: Optional[str]
    intent: Optional[str]
    token_usage: Optional[Dict[str, int]]
    file_path: Optional[str]
    file_content: Optional[str]
    # ===== 重构新增字段 =====
    skills_to_execute: Optional[List[str]]
    skill_results: Optional[List[dict]]
    retry_count: Optional[int]
    reflect_feedback: Optional[str]
    reflect_decision: Optional[str]
    history_summary: Optional[str]
    # ===== Plan-Execute 新增 =====
    execution_plan: Optional[List[dict]]  # planner 输出的顺序执行计划


# ReAct 循环最大重试次数(防止 LLM 抖动导致死循环)
MAX_RETRIES = 2