from typing import TypedDict, Optional, List, Dict


class AgentState(TypedDict):
    user_input: str
    conversation_id: Optional[str] = None
    history: Optional[List[Dict]] = None
    tool_result: Optional[dict] = None
    answer: Optional[str] = None
