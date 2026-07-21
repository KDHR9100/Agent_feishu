from typing import TypedDict, Optional, List, Dict


class AgentState(TypedDict, total=False):
    user_input: str
    conversation_id: Optional[str]
    history: Optional[List[Dict]]
    tool_result: Optional[dict]
    answer: Optional[str]
    intent: Optional[str]
    token_usage: Optional[Dict[str, int]]
