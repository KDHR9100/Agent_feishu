from typing import TypedDict, Optional, List, Dict


class AgentState(TypedDict, total=False):
    user_input: str
    conversation_id: Optional[str]
    history: Optional[List[Dict]]
    tool_result: Optional[dict]
    answer: Optional[str]
    intent: Optional[str]
    token_usage: Optional[Dict[str, int]]
    file_path: Optional[str]  # 下载后的文件路径
    file_content: Optional[str]  # 解析后的文件内容
    # ===== 重构新增字段 =====
    skills_to_execute: Optional[List[str]]  # router 输出的技能列表(支持多技能 fan-out)
    skill_results: Optional[List[dict]]  # skill_executor 累积的多技能结果
    retry_count: Optional[int]  # ReAct 反思循环计数
    reflect_feedback: Optional[str]  # 上次反思的反馈(注入下一轮 router)
    reflect_decision: Optional[str]  # reflect 节点的判断结果: sufficient/insufficient


# ReAct 循环最大重试次数(防止 LLM 抖动导致死循环)
MAX_RETRIES = 2
