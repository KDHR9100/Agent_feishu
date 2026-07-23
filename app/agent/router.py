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


def file_analysis_skill_router(user_input: str) -> dict:
    """Route user input to file analysis skill."""
    return {"skill": "file_analysis_skill", "user_input": user_input}


tools = [
    StructuredTool.from_function(product_skill_router),
    StructuredTool.from_function(ads_skill_router),
    StructuredTool.from_function(content_skill_router),
    StructuredTool.from_function(help_skill_router),
    StructuredTool.from_function(file_analysis_skill_router),
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
    file_path = state.get("file_path")
    file_content = state.get("file_content")
    history = state.get("history", [])

    # ============================================================
    # 关键逻辑 1：如果检测到文件内容，直接路由到文件解析技能
    # ============================================================
    # 当用户上传了文件且文件已解析出内容时，或者用户明确要求解析文件时
    if file_path and file_content:
        # 如果用户消息是空或是只有"[文件] xxx"，或者包含"解析"关键词
        is_empty_or_file_msg = (
            not user_input.strip() or
            user_input.strip().startswith("[文件]") or
            any(kw in user_input for kw in ["解析", "分析", "查看", "解读", "这个文件", "这份数据"])
        )
        if is_empty_or_file_msg:
            state["tool_result"] = {
                "skill": "file_analysis_skill",
                "user_input": user_input,
                "file_path": file_path,
                "file_content": file_content
            }
            state["intent"] = "file_analysis_skill"
            logger.info("[Router] File detected, directly routing to file_analysis_skill")
            return state

    # ============================================================
    # 关键逻辑 2：将历史上下文注入到路由 Prompt 中
    # ============================================================
    # 构建历史上下文字符串（最近 5 条）
    history_text = ""
    if history:
        history_lines = []
        for msg in history[-5:]:  # 最多取最近 5 条
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if role == "user":
                history_lines.append(f"用户: {content}")
            elif role == "assistant":
                history_lines.append(f"助手: {content}")
        history_text = "\n".join(history_lines)

    # 在 System Prompt 中追加历史上下文
    enhanced_prompt = ROUTER_PROMPT
    if history_text:
        enhanced_prompt = enhanced_prompt + f"\n\n## 历史对话上下文\n{history_text}\n\n请基于以上历史对话理解用户意图。如果用户说\"刚刚发的文档\"、\"刚才那个文件\"等，应结合历史上下文判断。"

    messages = [
        SystemMessage(content=enhanced_prompt),
        HumanMessage(content=user_input),
    ]

    response = llm_with_tools.invoke(messages)

    if response.tool_calls:
        tool_call = response.tool_calls[0]
        skill_name = tool_call["name"]
        params = tool_call["args"]

        # 如果路由到 file_analysis_skill，同时传递文件信息
        if skill_name == "file_analysis_skill" and file_path and file_content:
            params["file_path"] = file_path
            params["file_content"] = file_content

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