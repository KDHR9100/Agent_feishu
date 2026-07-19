from langchain_openai import ChatOpenAI
from langchain.tools import StructuredTool
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import config
from app.prompts import ROUTER_PROMPT


def product_skill_router(user_input: str) -> dict:
    return {"skill": "product_skill", "user_input": user_input}


def ads_skill_router(user_input: str) -> dict:
    return {"skill": "ads_skill", "user_input": user_input}


def content_skill_router(user_input: str) -> dict:
    return {"skill": "content_skill", "user_input": user_input}


tools = [
    StructuredTool.from_function(product_skill_router),
    StructuredTool.from_function(ads_skill_router),
    StructuredTool.from_function(content_skill_router),
]


llm = ChatOpenAI(
    model=config.OPENAI_MODEL_NAME,
    temperature=config.LLM_TEMPERATURE,
    max_tokens=config.LLM_MAX_TOKENS,
    api_key=config.OPENAI_API_KEY,
    base_url=config.OPENAI_API_BASE,
)


llm_with_tools = llm.bind_tools(tools)


def router(state):
    user_input = state["user_input"]
    
    messages = [
        SystemMessage(content=ROUTER_PROMPT),
        HumanMessage(content=user_input),
    ]
    
    response = llm_with_tools.invoke(messages)
    
    if response.tool_calls:
        tool_call = response.tool_calls[0]
        skill_name = tool_call["name"]
        params = tool_call["args"]
        state["tool_result"] = {"skill": skill_name, **params}
    else:
        state["tool_result"] = {
            "skill": "unknown",
            "user_input": user_input,
            "data": "鏃犳硶璇嗗埆浠诲姟锛岃閲嶆柊鎻忚堪"
        }
    
    return state
