import re
import logging
import time
from langgraph.graph import StateGraph
from langchain_core.messages import HumanMessage, SystemMessage

from .state import AgentState
from .router import router
from app.memory.local_memory import local_memory
from app.config import get_llm
from app.utils.timeout import timeout
from app.monitoring import monitoring_stats

logger = logging.getLogger("workflow")


def strip_thinking(text):
    if not isinstance(text, str):
        return text
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[-1]
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"<think>.*", "", text, flags=re.DOTALL)
    text = re.sub(
        r"^Here'?s a thinking process:.*$", "", text, flags=re.MULTILINE | re.DOTALL
    )
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


def load_file(state):
    """解析上传的文件，将内容存入 state['file_content']"""
    file_path = state.get("file_path")
    if not file_path:
        return state

    try:
        from app.tools.file_parser_tool import file_parser_tool
        import os

        # 检查文件是否存在
        if not os.path.exists(file_path):
            logger.warning("[Workflow] File not found: %s" % file_path)
            state["file_content"] = None
            return state

        # 使用 file_parser_tool 解析文件
        result = file_parser_tool.parse_local_file(file_path)
        if result.get("error"):
            logger.error("[Workflow] File parse error: %s" % result.get("error"))
            state["file_content"] = None
        else:
            # 将解析结果格式化为文本，方便后续 LLM 使用
            summary = result.get("summary", {})
            columns = result.get("columns", [])
            row_count = result.get("row_count", 0)
            sample_rows = result.get("sample_rows", [])

            content_parts = [
                f"文件信息: {file_path}",
                f"列: {', '.join(columns)}",
                f"行数: {row_count}",
                "数据摘要:",
            ]
            for col, info in summary.items():
                if info.get("type") == "numeric":
                    content_parts.append(
                        f"  - {col}: 均值={info.get('mean', 'N/A'):.2f}, 最大={info.get('max', 'N/A')}, 最小={info.get('min', 'N/A')}"
                    )
                else:
                    content_parts.append(
                        f"  - {col}: 去重数={info.get('unique_count', 'N/A')}, 样例={info.get('sample_values', [])}"
                    )

            if sample_rows:
                content_parts.append("数据样例 (前3行):")
                for i, row in enumerate(sample_rows):
                    content_parts.append(f"  第{i+1}行: {row}")

            state["file_content"] = "\n".join(content_parts)
            logger.info(
                "[Workflow] File parsed successfully: %s, %d rows, %d columns"
                % (file_path, row_count, len(columns))
            )

    except Exception as e:
        logger.error("[Workflow] Failed to parse file: %s" % str(e))
        state["file_content"] = None

    return state


@timeout(30)
def _call_llm(llm, messages):
    return llm.invoke(messages)


def skill_executor(state):
    tool_result = state["tool_result"]
    skill = tool_result.get("skill")
    user_input = tool_result.get("user_input", "")
    state["token_usage"] = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }

    skill_start = time.time()
    if skill == "product_skill":
        from app.skills.product_skill import product_skill

        result = product_skill(user_input)
        monitoring_stats.record_skill_call("product_skill", time.time() - skill_start)
    elif skill == "ads_skill":
        from app.skills.ads_skill import ads_skill

        result = ads_skill(user_input)
        monitoring_stats.record_skill_call("ads_skill", time.time() - skill_start)
    elif skill == "content_skill":
        from app.skills.content_skill import content_skill

        result = content_skill(user_input)
        monitoring_stats.record_skill_call("content_skill", time.time() - skill_start)
    elif skill == "help_skill":
        from app.skills.help_skill import help_skill

        result = help_skill(user_input)
        monitoring_stats.record_skill_call("help_skill", time.time() - skill_start)
    # ============================================================
    # 新增：文件解析技能分支
    # ============================================================
    elif skill == "file_analysis_skill":
        from app.skills.file_analysis_skill import file_analysis_skill

        file_path = tool_result.get("file_path")
        file_content = tool_result.get("file_content") or state.get("file_content")
        result = file_analysis_skill(user_input, file_path, file_content)
        monitoring_stats.record_skill_call(
            "file_analysis_skill", time.time() - skill_start
        )
    else:
        llm = get_llm()
        system_msg = SystemMessage(
            content=(
                "You are an Ecommerce Agent assistant. For questions that cannot be categorized "
                "into specific business skills (such as greetings, identity inquiries, casual chat, etc.), "
                "please answer directly in Chinese in a friendly manner."
            )
        )
        human_msg = HumanMessage(content=user_input)
        llm_start = time.time()
        try:
            response = _call_llm(llm, [system_msg, human_msg])
            llm_duration = time.time() - llm_start
            monitoring_stats.record_llm_call(llm_duration)

            reply = response.content if hasattr(response, "content") else str(response)
            reply = strip_thinking(reply)

            if hasattr(response, "response_metadata") and response.response_metadata:
                token_usage = response.response_metadata.get("token_usage", {})
                state["token_usage"] = {
                    "prompt_tokens": token_usage.get("prompt_tokens", 0),
                    "completion_tokens": token_usage.get("completion_tokens", 0),
                    "total_tokens": token_usage.get("total_tokens", 0),
                }
                monitoring_stats.record_llm_call(
                    llm_duration, token_usage=state["token_usage"]
                )
                logger.info(
                    "[Workflow] LLM Token Usage - Prompt: %d, Completion: %d, Total: %d"
                    % (
                        state["token_usage"]["prompt_tokens"],
                        state["token_usage"]["completion_tokens"],
                        state["token_usage"]["total_tokens"],
                    )
                )
        except Exception as e:
            reply = "Error processing request: %s" % str(e)
            monitoring_stats.record_llm_call(time.time() - llm_start, success=False)
            logger.error("[Workflow] LLM invoke error: %s" % str(e))
        result = {"type": "chat", "data": reply}

    state["tool_result"] = result
    return state


def answer_node(state):
    result = state["tool_result"]
    if isinstance(result, dict):
        data = result.get("data", "")
        if isinstance(data, dict):
            text = (
                data.get("analysis")
                or data.get("copy")
                or data.get("response")
                or str(data)
            )
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
graph.add_node("load_file", load_file)  # 新增：文件解析节点
graph.add_node("router", router)
graph.add_node("skill_executor", skill_executor)
graph.add_node("answer", answer_node)
graph.add_node("save_history", save_history)

graph.set_entry_point("load_history")
graph.add_edge("load_history", "load_file")  # 先加载文件再路由
graph.add_edge("load_file", "router")
graph.add_edge("router", "skill_executor")
graph.add_edge("skill_executor", "answer")
graph.add_edge("answer", "save_history")

agent = graph.compile()
