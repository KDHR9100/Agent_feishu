from typing import TypedDict


class AgentState(TypedDict):

    user_input: str

    tool_result: dict

    answer: str