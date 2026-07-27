import re
import logging
import time
from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

from .state import AgentState, MAX_RETRIES
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
    logger.info(
        "[load_history] conversation_id=%s, messages_loaded=%d"
        % (conversation_id, len(state["history"]))
    )
    return state


def save_history(state):
    conversation_id = state.get("conversation_id", "default")
    answer = str(state["answer"])
    local_memory.add_message(conversation_id, "user", state["user_input"])
    local_memory.add_message(conversation_id, "assistant", answer)
    logger.info(
        "[save_history] conversation_id=%s, user_msg_len=%d, assistant_msg_len=%d"
        % (conversation_id, len(state["user_input"]), len(answer))
    )
    return state


def load_file(state):
    """解析上传的文件，将内容存入 state['file_content']"""
    file_path = state.get("file_path")
    if not file_path:
        logger.info("[load_file] no file_path, skipping")
        return state

    logger.info("[load_file] file_path=%s" % file_path)
    try:
        from app.tools.file_parser_tool import file_parser_tool
        import os

        if not os.path.exists(file_path):
            logger.warning("[load_file] file not found: %s" % file_path)
            state["file_content"] = None
            return state

        result = file_parser_tool.parse_local_file(file_path)
        if result.get("error"):
            logger.error("[load_file] parse error: %s" % result.get("error"))
            state["file_content"] = None
        else:
            state["file_content"] = file_parser_tool.format_file_summary(
                result, os.path.basename(file_path)
            )
            logger.info(
                "[load_file] parse OK, rows=%d, content_len=%d"
                % (result.get("row_count", 0), len(state["file_content"] or ""))
            )
    except Exception as e:
        logger.error("[load_file] exception: %s" % str(e), exc_info=True)
        state["file_content"] = None
    return state


@timeout(30)
def _call_llm(llm, messages):
    return llm.invoke(messages)


# ============================================================
# 技能注册表: 替代原 if-elif 链
# ============================================================
def _run_product_skill(user_input, file_path, file_content, tool_result):
    from app.skills.product_skill import product_skill
    return product_skill(user_input)


def _run_ads_skill(user_input, file_path, file_content, tool_result):
    from app.skills.ads_skill import ads_skill
    return ads_skill(user_input)


def _run_content_skill(user_input, file_path, file_content, tool_result):
    from app.skills.content_skill import content_skill
    return content_skill(user_input)


def _run_help_skill(user_input, file_path, file_content, tool_result):
    from app.skills.help_skill import help_skill
    return help_skill(user_input)


def _run_file_analysis_skill(user_input, file_path, file_content, tool_result):
    from app.skills.file_analysis_skill import file_analysis_skill
    fp = tool_result.get("file_path") or file_path
    fc = tool_result.get("file_content") or file_content
    return file_analysis_skill(user_input, fp, fc)


SKILL_REGISTRY = {
    "product_skill": _run_product_skill,
    "ads_skill": _run_ads_skill,
    "content_skill": _run_content_skill,
    "help_skill": _run_help_skill,
    "file_analysis_skill": _run_file_analysis_skill,
}


def _run_unknown_skill(state, user_input):
    """兜底分支: 非电商场景的闲聊直接走 LLM"""
    logger.info("[skill_executor:unknown] using LLM direct answer")
    llm = get_llm()
    system_msg = SystemMessage(
        content=(
            "You are an Ecommerce Agent assistant. For questions that cannot be categorized "
            "into specific business skills (such as greetings, identity inquiries, casual chat, etc.), "
            "please answer directly in Chinese in a friendly manner."
        )
    )
    messages = [system_msg]
    history = state.get("history", [])
    for msg in history:
        role = msg.get("role", "")
        msg_content = msg.get("content", "")
        if role == "user":
            messages.append(HumanMessage(content=msg_content))
        elif role == "assistant":
            messages.append(AIMessage(content=msg_content))
    messages.append(HumanMessage(content=user_input))

    llm_start = time.time()
    try:
        response = _call_llm(llm, messages)
        llm_duration = time.time() - llm_start
        monitoring_stats.record_llm_call(llm_duration)

        reply = response.content if hasattr(response, "content") else str(response)
        reply = strip_thinking(reply)

        token_usage_dict = {}
        if hasattr(response, "response_metadata") and response.response_metadata:
            tu = response.response_metadata.get("token_usage", {})
            token_usage_dict = {
                "prompt_tokens": tu.get("prompt_tokens", 0),
                "completion_tokens": tu.get("completion_tokens", 0),
                "total_tokens": tu.get("total_tokens", 0),
            }
            monitoring_stats.record_llm_call(llm_duration, token_usage=token_usage_dict)
            logger.info(
                "[skill_executor:unknown] LLM tokens: prompt=%d, completion=%d, total=%d"
                % (
                    token_usage_dict["prompt_tokens"],
                    token_usage_dict["completion_tokens"],
                    token_usage_dict["total_tokens"],
                )
            )
        _accumulate_token_usage(state, token_usage_dict)
        logger.info(
            "[skill_executor:unknown] LLM reply_len=%d, duration=%.2fs"
            % (len(reply), llm_duration)
        )
    except Exception as e:
        reply = "Error processing request: %s" % str(e)
        monitoring_stats.record_llm_call(time.time() - llm_start, success=False)
        logger.error("[skill_executor:unknown] LLM error: %s" % str(e))
    return {"type": "chat", "data": reply}


def _accumulate_token_usage(state, delta):
    """累加 token 用量(多技能时聚合)"""
    if not delta:
        return
    cur = state.get("token_usage") or {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    cur["prompt_tokens"] += delta.get("prompt_tokens", 0)
    cur["completion_tokens"] += delta.get("completion_tokens", 0)
    cur["total_tokens"] += delta.get("total_tokens", 0)
    state["token_usage"] = cur


def skill_executor(state):
    """注册表模式 + 多技能迭代执行"""
    tool_result = state.get("tool_result") or {}
    user_input = tool_result.get("user_input", "")
    file_path = state.get("file_path")
    file_content = state.get("file_content")

    skills = state.get("skills_to_execute") or [tool_result.get("skill", "unknown")]
    state["token_usage"] = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    results = []

    logger.info(
        "[skill_executor] starting %d skill(s): %s" % (len(skills), skills)
    )

    for idx, skill_name in enumerate(skills, 1):
        skill_start = time.time()
        logger.info(
            "[skill_executor] (%d/%d) running skill=%s"
            % (idx, len(skills), skill_name)
        )
        try:
            if skill_name in SKILL_REGISTRY:
                result = SKILL_REGISTRY[skill_name](
                    user_input, file_path, file_content, tool_result
                )
                monitoring_stats.record_skill_call(
                    skill_name, time.time() - skill_start
                )
            elif skill_name == "unknown":
                result = _run_unknown_skill(state, user_input)
            else:
                logger.warning(
                    "[skill_executor] unknown skill=%s, fallback to unknown"
                    % skill_name
                )
                result = _run_unknown_skill(state, user_input)
        except Exception as e:
            logger.error(
                "[skill_executor] skill=%s error: %s" % (skill_name, str(e)),
                exc_info=True,
            )
            result = {
                "type": "error",
                "data": "技能 %s 执行出错, 请稍后重试。" % skill_name,
            }
            monitoring_stats.record_skill_call(
                skill_name, time.time() - skill_start, success=False
            )

        duration = time.time() - skill_start
        result_type = result.get("type", "unknown") if isinstance(result, dict) else type(result).__name__
        logger.info(
            "[skill_executor] (%d/%d) skill=%s done, duration=%.2fs, type=%s"
            % (idx, len(skills), skill_name, duration, result_type)
        )
        results.append({"skill": skill_name, "result": result})

    state["skill_results"] = results
    if results:
        state["tool_result"] = results[0]["result"]
    logger.info(
        "[skill_executor] all done, results_count=%d, total_tokens=%d"
        % (len(results), state["token_usage"].get("total_tokens", 0))
    )
    return state


# ============================================================
# ReAct 反思节点
# ============================================================
REFLECT_PROMPT_TEMPLATE = """你是一个电商运营Agent的回答质量审查员。

用户原始问题:
{user_input}

技能执行结果(可能多个):
{skill_results_text}

请判断以上结果是否充分回答了用户的问题。

判断标准:
- "sufficient": 结果直接回答了用户问题, 信息完整可用
- "insufficient": 结果缺失关键信息, 或答非所问, 需要换技能/补技能

请只返回 JSON, 格式:
{{"decision": "sufficient" 或 "insufficient", "feedback": "如果 insufficient, 简要说明缺什么/建议换什么技能"}}

注意: 如果技能已经报错或返回兜底文本, 视为 insufficient。
"""


@timeout(20)
def _reflect_llm_call(llm, messages):
    return llm.invoke(messages)


def reflect(state):
    """ReAct 反思节点: 判断是否需要回边重试"""
    skills = state.get("skills_to_execute") or []

    # 文件场景短路
    if len(skills) == 1 and skills[0] == "file_analysis_skill":
        logger.info("[reflect] file_analysis shortcut, skipping reflection")
        state["reflect_decision"] = "sufficient"
        return state

    results = state.get("skill_results") or []
    if not results:
        logger.warning("[reflect] no skill_results, forcing sufficient")
        state["reflect_decision"] = "sufficient"
        return state

    retry_count = state.get("retry_count") or 0
    if retry_count >= MAX_RETRIES:
        logger.info(
            "[reflect] retry_count=%d >= MAX_RETRIES=%d, forcing sufficient"
            % (retry_count, MAX_RETRIES)
        )
        state["reflect_decision"] = "sufficient"
        return state

    logger.info(
        "[reflect] reviewing %d result(s), retry_count=%d/%d"
        % (len(results), retry_count, MAX_RETRIES)
    )

    user_input = state.get("user_input", "")
    results_text_parts = []
    for item in results:
        sname = item.get("skill", "unknown")
        sres = item.get("result", {})
        data = sres.get("data") if isinstance(sres, dict) else str(sres)
        if isinstance(data, dict):
            data = data.get("analysis") or data.get("copy") or data.get("response") or str(data)
        results_text_parts.append("- [%s]: %s" % (sname, str(data)[:500]))
    skill_results_text = "\n".join(results_text_parts)

    prompt = REFLECT_PROMPT_TEMPLATE.format(
        user_input=user_input[:500], skill_results_text=skill_results_text
    )

    try:
        llm = get_llm()
        reflect_start = time.time()
        response = _reflect_llm_call(llm, [HumanMessage(content=prompt)])
        raw = response.content if hasattr(response, "content") else str(response)
        raw = strip_thinking(raw)
        logger.info(
            "[reflect] LLM responded in %.2fs, raw_len=%d"
            % (time.time() - reflect_start, len(raw))
        )

        import json as _json
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            decision = "sufficient"
            feedback = ""
            logger.warning("[reflect] no JSON found in response, default=sufficient")
        else:
            parsed = _json.loads(m.group(0))
            decision = parsed.get("decision", "sufficient")
            feedback = parsed.get("feedback", "")
    except Exception as e:
        logger.warning(
            "[reflect] LLM error, fail-open to sufficient: %s" % str(e)
        )
        decision = "sufficient"
        feedback = ""

    state["reflect_decision"] = decision
    if decision == "insufficient" and feedback:
        state["reflect_feedback"] = feedback
        state["retry_count"] = retry_count + 1
        logger.info(
            "[reflect] decision=insufficient, will retry (count=%d), feedback=%s"
            % (state["retry_count"], feedback[:100])
        )
    else:
        logger.info(
            "[reflect] decision=sufficient, proceed to answer"
        )
    return state


def _route_after_reflect(state):
    """条件边: reflect 后的去向"""
    if state.get("reflect_decision") == "insufficient":
        logger.info("[route_after_reflect] → router (retry)")
        return "router"
    logger.info("[route_after_reflect] → answer")
    return "answer"


# ============================================================
# Answer 节点
# ============================================================
SUMMARIZATION_PROMPT_TEMPLATE = """你是一个电商运营Agent的综合回答专家。

用户原始问题:
{user_input}

多个技能的执行结果:
{skill_results_text}

请基于以上结果, 综合生成一份连贯、专业、对用户友好的中文回答。
要求:
1. 整合不同技能的输出, 避免简单拼接
2. 突出关键数据和结论
3. 如果结果中有冲突, 给出说明
4. 用 Markdown 格式输出, 必要时分点列举

请直接输出综合回答, 不要解释你在做什么。
"""


def _extract_text_from_result(result_obj):
    if not isinstance(result_obj, dict):
        return str(result_obj)
    data = result_obj.get("data", "")
    if isinstance(data, dict):
        text = (
            data.get("analysis")
            or data.get("copy")
            or data.get("response")
            or str(data)
        )
    elif isinstance(data, str):
        text = data
    else:
        text = str(result_obj)
    return strip_thinking(text) or str(result_obj)


def answer_node(state):
    results = state.get("skill_results") or []

    # 单结果快路径
    if len(results) <= 1:
        single = results[0]["result"] if results else state.get("tool_result")
        answer_text = _extract_text_from_result(single)
        state["answer"] = strip_thinking(answer_text) or str(single)
        logger.info(
            "[answer] single-result path, answer_len=%d" % len(state["answer"])
        )
        return state

    # 多结果综合路径
    logger.info(
        "[answer] multi-result path, synthesizing %d results" % len(results)
    )
    user_input = state.get("user_input", "")
    parts = []
    for item in results:
        sname = item.get("skill", "unknown")
        text = _extract_text_from_result(item.get("result", {}))
        parts.append("### 技能: %s\n%s" % (sname, text[:2000]))
    skill_results_text = "\n\n".join(parts)

    prompt = SUMMARIZATION_PROMPT_TEMPLATE.format(
        user_input=user_input[:500], skill_results_text=skill_results_text
    )

    try:
        llm = get_llm()
        synth_start = time.time()
        response = _call_llm(llm, [HumanMessage(content=prompt)])
        reply = response.content if hasattr(response, "content") else str(response)
        reply = strip_thinking(reply)

        if hasattr(response, "response_metadata") and response.response_metadata:
            tu = response.response_metadata.get("token_usage", {})
            _accumulate_token_usage(state, tu)

        logger.info(
            "[answer] synthesis done in %.2fs, answer_len=%d"
            % (time.time() - synth_start, len(reply))
        )
    except Exception as e:
        logger.error("[answer] synthesis error, fallback to join: %s" % str(e))
        reply = "\n\n---\n\n".join(
            _extract_text_from_result(item.get("result", {})) for item in results
        )

    state["answer"] = reply
    return state


# ============================================================
# 拼装 LangGraph
# ============================================================
graph = StateGraph(AgentState)

graph.add_node("load_history", load_history)
graph.add_node("load_file", load_file)
graph.add_node("router", router)
graph.add_node("skill_executor", skill_executor)
graph.add_node("reflect", reflect)
graph.add_node("answer", answer_node)
graph.add_node("save_history", save_history)

graph.set_entry_point("load_history")
graph.add_edge("load_history", "load_file")
graph.add_edge("load_file", "router")
graph.add_edge("router", "skill_executor")
graph.add_edge("skill_executor", "reflect")
graph.add_conditional_edges(
    "reflect",
    _route_after_reflect,
    {"router": "router", "answer": "answer"},
)
graph.add_edge("answer", "save_history")
graph.add_edge("save_history", END)

agent = graph.compile()
