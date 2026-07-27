import logging
import time
from langchain_core.tools import StructuredTool
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_llm
from app.prompts import ROUTER_PROMPT

logger = logging.getLogger("router")


# ============================================================
# Tool 函数: 名字必须与 SKILL_REGISTRY 的 key 一致
# ============================================================
def product_skill(user_input: str) -> dict:
    """分析商品销售数据、库存、SKU表现等"""
    return {"skill": "product_skill", "user_input": user_input}


def ads_skill(user_input: str) -> dict:
    """分析广告投放效果、ROI、花费等"""
    return {"skill": "ads_skill", "user_input": user_input}


def content_skill(user_input: str) -> dict:
    """生成营销文案、商品描述、推广内容等"""
    return {"skill": "content_skill", "user_input": user_input}


def help_skill(user_input: str) -> dict:
    """提供使用帮助和功能导航"""
    return {"skill": "help_skill", "user_input": user_input}


def file_analysis_skill(user_input: str) -> dict:
    """解析上传的文件数据(xlsx/csv/pdf/docx)"""
    return {"skill": "file_analysis_skill", "user_input": user_input}


def inventory_skill(user_input: str) -> dict:
    """分析库存数据、库存预警、补货建议等"""
    return {"skill": "inventory_skill", "user_input": user_input}


def competitor_skill(user_input: str) -> dict:
    """分析竞品数据、市场竞争情报等"""
    return {"skill": "competitor_skill", "user_input": user_input}


def report_skill(user_input: str) -> dict:
    """生成运营报告、数据报告、分析报告等"""
    return {"skill": "report_skill", "user_input": user_input}


def rag_skill(user_input: str) -> dict:
    """基于知识库的检索增强问答(RAG)"""
    return {"skill": "rag_skill", "user_input": user_input}


def seo_skill(user_input: str) -> dict:
    """SEO优化分析、关键词研究、标题优化等"""
    return {"skill": "seo_skill", "user_input": user_input}


def support_skill(user_input: str) -> dict:
    """客服支持、订单查询、退换货处理、售后问题等"""
    return {"skill": "support_skill", "user_input": user_input}


def data_analysis_skill(user_input: str) -> dict:
    """数据分析、趋势分析、异常检测、统计报告等"""
    return {"skill": "data_analysis_skill", "user_input": user_input}


tools = [
    StructuredTool.from_function(product_skill),
    StructuredTool.from_function(ads_skill),
    StructuredTool.from_function(content_skill),
    StructuredTool.from_function(help_skill),
    StructuredTool.from_function(file_analysis_skill),
    StructuredTool.from_function(inventory_skill),
    StructuredTool.from_function(competitor_skill),
    StructuredTool.from_function(report_skill),
    StructuredTool.from_function(rag_skill),
    StructuredTool.from_function(seo_skill),
    StructuredTool.from_function(support_skill),
    StructuredTool.from_function(data_analysis_skill),
]


_llm_with_tools = None


def _get_llm_with_tools():
    global _llm_with_tools
    if _llm_with_tools is None:
        _llm = get_llm()
        _llm_with_tools = _llm.bind_tools(tools)
    return _llm_with_tools


def router(state):
    user_input = state["user_input"]
    file_path = state.get("file_path")
    file_content = state.get("file_content")
    history = state.get("history", [])

    logger.info(
        "[router] user_input=%s, conversation_id=%s, has_file=%s"
        % (
            user_input[:80] + ("..." if len(user_input) > 80 else ""),
            state.get("conversation_id", "default"),
            bool(file_path),
        )
    )

    # ============================================================
    # 文件场景短路
    # ============================================================
    if file_path and file_content:
        is_empty_or_file_msg = (
            not user_input.strip()
            or user_input.strip().startswith("[文件]")
            or any(
                kw in user_input
                for kw in ["解析", "分析", "查看", "解读", "这个文件", "这份数据"]
            )
        )
        if is_empty_or_file_msg:
            state["tool_result"] = {
                "skill": "file_analysis_skill",
                "user_input": user_input,
                "file_path": file_path,
                "file_content": file_content,
            }
            state["skills_to_execute"] = ["file_analysis_skill"]
            state["intent"] = "file_analysis_skill"
            logger.info(
                "[router] file shortcut → file_analysis_skill, file_path=%s"
                % file_path
            )
            return state

    # ============================================================
    # 历史上下文注入
    # ============================================================
    history_text = ""
    if history:
        history_lines = []
        for msg in history[-5:]:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if role == "user":
                history_lines.append(f"用户: {content}")
            elif role == "assistant":
                history_lines.append(f"助手: {content}")
        history_text = "\n".join(history_lines)
        logger.info("[router] history injected, %d messages" % len(history[-5:]))

    enhanced_prompt = ROUTER_PROMPT
    if history_text:
        enhanced_prompt = (
            enhanced_prompt
            + f'\n\n## 历史对话上下文\n{history_text}\n\n请基于以上历史对话理解用户意图时如果用户说"刚刚发的文档"、"刚才那个文件"等，,应结合历史上下文判断。'
        )

    # ===== ReAct 回边: 注入反思反馈 =====
    reflect_feedback = state.get("reflect_feedback")
    if reflect_feedback:
        enhanced_prompt = (
            enhanced_prompt
            + f"\n\n## 上次执行反思反馈\n{reflect_feedback}\n\n请基于以上反馈重新选择更合适的技能组合。"
        )
        state["reflect_feedback"] = None
        logger.info(
            "[router] reflect_feedback injected (retry), feedback=%s"
            % reflect_feedback[:100]
        )

    messages = [
        SystemMessage(content=enhanced_prompt),
        HumanMessage(content=user_input),
    ]

    logger.info("[router] calling LLM with tools...")
    router_start = time.time()
    llm_with_tools = _get_llm_with_tools()
    response = llm_with_tools.invoke(messages)
    router_duration = time.time() - router_start
    logger.info(
        "[router] LLM responded in %.2fs, has_tool_calls=%s"
        % (router_duration, bool(response.tool_calls))
    )

    if response.tool_calls:
        selected_skills = [tc["name"] for tc in response.tool_calls]
        first_params = response.tool_calls[0]["args"]

        if "file_analysis_skill" in selected_skills and file_path and file_content:
            first_params["file_path"] = file_path
            first_params["file_content"] = file_content

        state["tool_result"] = {"skill": selected_skills[0], **first_params}
        state["skills_to_execute"] = selected_skills
        state["intent"] = selected_skills[0]
        logger.info(
            "[router] selected %d skill(s): %s"
            % (len(selected_skills), "+".join(selected_skills))
        )
    else:
        state["tool_result"] = {
            "skill": "unknown",
            "user_input": user_input,
            "data": "Unable to recognize the task, please rephrase.",
        }
        state["skills_to_execute"] = ["unknown"]
        state["intent"] = "unknown"
        logger.warning("[router] no tool_calls, intent=unknown")

    if hasattr(response, "response_metadata") and response.response_metadata:
        token_usage = response.response_metadata.get("token_usage", {})
        logger.info(
            "[router] tokens: prompt=%d, completion=%d, total=%d"
            % (
                token_usage.get("prompt_tokens", 0),
                token_usage.get("completion_tokens", 0),
                token_usage.get("total_tokens", 0),
            )
        )

    return state
