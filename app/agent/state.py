from typing import TypedDict, Optional, List, Dict


class AgentState(TypedDict, total=False):
    user_input: str
    conversation_id: Optional[str]
    history: Optional[List[Dict]]
    tool_result: Optional[dict]
    answer: Optional[str]
    intent: Optional[str]
    token_usage: Optional[Dict[str, int]]
    file_path: Optional[str]          # 新增：下载后的文件路径
    file_content: Optional[str]       # 新增：解析后的文件内容