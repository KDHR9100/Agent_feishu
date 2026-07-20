import re
from langgraph.graph import StateGraph
from langchain_core.messages import HumanMessage, SystemMessage

from .state import AgentState
from .router import router
from app.memory.local_memory import local_memory
from app.config import get_llm


def strip_thinking(text):
    """Remove thinking process from LLM output (qwen3 thinking mode)."""
    if not isinstance(text, str):
        return text
    # qwen3 may output thinking in various formats:
    #   <think>...</think>
    #   Here is a thinking process: ... </think>
    #   <think>... (unclosed)
    # Strategy: if </think> exists, take everything after the LAST </think>
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[-1]
    # Remove any remaining <think> tags and their content
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"<think>.*", "", text, flags=re.DOTALL)
    # Also strip common thinking-process prefixes that may appear without tags
    # e.g. "Here's a thinking process:", "Here is a thinking process:"
    text = re.sub(r"^Here'?s a thinking process:.*$", "", text, flags=re.MULTILINE | re.DOTALL)
    return text.strip()


def load_history(state):
    conversation_id = state.get("conversation_id", "default")
    state["history"] = local_memory.get_last_n_messages(conversation_id, n=5)
    return state


def save_history(state):
    conversation_id = state.get("conversation_id", "default")
    local_memory.add_message(conversation_id, "user", state["user_input"])
    local_memory.add_message(conversation_id, "assistant", str(state["answer"]))
    return state


def skill_executor(state):
    tool_result = state["tool_result"]
    skill = tool_result.get("skill")
    user_input = tool_result.get("user_input", "")

    if skill == "product_skill":
        from app.skills.product_skill import product_skill
        result = product_skill(user_input)
    elif skill == "ads_skill":
        from app.skills.ads_skill import ads_skill
        result = ads_skill(user_input)
    elif skill == "content_skill":
        from app.skills.content_skill import content_skill
        result = content_skill(user_input)
    else:
        llm = get_llm()
        system_msg = SystemMessage(content=(
            "你是一个电商运营Agent助手。对于无法归类到具体业务技能的问题"
            "（如问候、身份询问、闲聊等），请直接用中文友好地回答。"
            "如果用户询问你是谁，请简要介绍你是电商运营Agent，"
            "可以帮忙做商品分析、广告分析、内容生成等。"
        ))
        human_msg = HumanMessage(content=user_input)
        try:
            response = llm.invoke([system_msg, human_msg])
            reply = response.content if hasattr(response, "content") else str(response)
            reply = strip_thinking(reply)
        except Exception as e:
            reply = "抱歉，处理请求时出错：%s" % str(e)
        result = {"type": "chat", "data": reply}

    state["tool_result"] = result
    return state


def answer_node(state):
    result = state["tool_result"]
    if isinstance(result, dict):
        data = result.get("data", "")
        if isinstance(data, dict):
            # Skills return dict with analysis/copy field
            text = data.get("analysis") or data.get("copy") or str(data)
            state["answer"] = strip_thinking(text)
        elif isinstance(data, str):
            state["answer"] = strip_thinking(data) or str(result)
        else:
            state["answer"] = str(result)
    else:
        state["answer"] = strip_thinking(str(result))
    return state


graph = StateGraph(AgentState)


graph.add_node("load_history", load_history)
graph.add_node("router", router)
graph.add_node("skill_executor", skill_executor)
graph.add_node("answer", answer_node)
graph.add_node("save_history", save_history)


graph.set_entry_point("load_history")


graph.add_edge("load_history", "router")
graph.add_edge("router", "skill_executor")
graph.add_edge("skill_executor", "answer")
graph.add_edge("answer", "save_history")


agent = graph.compile()
