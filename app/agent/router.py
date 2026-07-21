import logging
from langchain_openai import ChatOpenAI
from langchain_core.tools import StructuredTool
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import config
from app.prompts import ROUTER_PROMPT

logger = logging.getLogger("router")


def product_skill_router(user_input: str) -> dict:
    """Route user input to product analysis skill."""
    return {"skill": "product_skill", "user_input": user_input}


def ads_skill_router(user_input: str) -> dict:
    """Route user input to ads analysis skill."""
    return {"skill": "ads_skill", "user_input": user_input}


def content_skill_router(user_input: str) -> dict:
    """Route user input to content generation skill."""
    return {"skill": "content_skill", "user_input": user_input}


def help_skill_router(user_input: str) -> dict:
    """Route user input to help/guide skill."""
    return {"skill": "help_skill", "user_input": user_input}


tools = [
    StructuredTool.from_function(product_skill_router),
    StructuredTool.from_function(ads_skill_router),
    StructuredTool.from_function(content_skill_router),
    StructuredTool.from_function(help_skill_router),
]


llm = ChatOpenAI(
    model=config.OPENAI_MODEL_NAME,
    temperature=config.LLM_TEMPERATURE,
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
        state["intent"] = skill_name
        logger.info("[Router] Intent recognized: %s - User input: %s" % (skill_name, user_input[:50] + "..." if len(user_input) > 50 else user_input))
    else:
        state["tool_result"] = {
            "skill": "unknown",
            "user_input": user_input,
            "data": "Unable to recognize the task, please rephrase."
        }
        state["intent"] = "unknown"
        logger.info("[Router] Intent not recognized - User input: %s" % (user_input[:50] + "..." if len(user_input) > 50 else user_input))

    if hasattr(response, "response_metadata") and response.response_metadata:
        token_usage = response.response_metadata.get("token_usage", {})
        logger.info("[Router] Token Usage - Prompt: %d, Completion: %d, Total: %d" % (
            token_usage.get("prompt_tokens", 0),
            token_usage.get("completion_tokens", 0),
            token_usage.get("total_tokens", 0)
        ))

    return state