import logging
import time
from langchain_core.tools import StructuredTool
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_llm
from app.prompts import ROUTER_PROMPT
from app.utils.timeout import timeout, TimeoutException

logger = logging.getLogger("router")


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

# ============================================================
# Keyword fallback: only activated when LLM fails/times out
# ============================================================
KEYWORD_RULES = {
    "product_skill": ["商品", "销量", "SKU", "sku", "评价", "商品分析", "卖得"],
    "ads_skill": ["广告", "投放", "ROI", "roi", "推广", "花费", "渠道"],
    "content_skill": ["文案", "活动策划", "营销", "推广文案", "写一段"],
    "inventory_skill": ["库存", "补货", "预警", "周转", "缺货"],
    "competitor_skill": ["竞品", "竞争", "对手", "市场情报"],
    "report_skill": ["报告", "周报", "月报", "汇总"],
    "rag_skill": ["规则", "佣金", "上架", "平台规则", "怎么算"],
    "seo_skill": ["SEO", "seo", "关键词", "搜索量", "标题优化", "长尾词"],
    "support_skill": ["订单", "退款", "退货", "售后", "客服", "物流"],
    "data_analysis_skill": ["趋势", "异常", "同比", "环比", "统计"],
    "file_analysis_skill": ["解析文件", "分析文件", "这个表格", "这份数据"],
    "help_skill": ["帮助", "你能做什么", "功能", "怎么用"],
}


def _keyword_scores(user_input: str) -> dict:
    input_lower = user_input.lower()
    scores = {}
    for skill, keywords in KEYWORD_RULES.items():
        hit_count = sum(1 for kw in keywords if kw.lower() in input_lower)
        if hit_count > 0:
            scores[skill] = hit_count
    return scores


def keyword_fallback(user_input: str) -> list:
    """基于关键词匹配返回技能列表，无匹配时返回空列表"""
    scores = _keyword_scores(user_input)
    if not scores:
        return []
    best = max(scores, key=scores.get)
    return [best]


_llm_with_tools = None


def _get_llm_with_tools():
    global _llm_with_tools
    if _llm_with_tools is None:
        _llm = get_llm()
        _llm_with_tools = _llm.bind_tools(tools)
    return _llm_with_tools


@timeout(20)
def _router_llm_call(llm_with_tools, messages):
    """带超时保护的路由 LLM 调用"""
    return llm_with_tools.invoke(messages)

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
            logger.info("[router] file shortcut -> file_analysis_skill")
            return state

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

    enhanced_prompt = ROUTER_PROMPT
    if history_text:
        enhanced_prompt += "\n\n## 历史对话上下文\n" + history_text

    reflect_feedback = state.get("reflect_feedback")
    if reflect_feedback:
        enhanced_prompt += "\n\n## 反思反馈\n" + reflect_feedback
        state["reflect_feedback"] = None

    messages = [
        SystemMessage(content=enhanced_prompt),
        HumanMessage(content=user_input),
    ]
    # LLM routing with timeout + keyword fallback
    logger.info("[router] calling LLM with tools...")
    router_start = time.time()
    response = None
    llm_failed = False

    try:
        llm_with_tools = _get_llm_with_tools()
        response = _router_llm_call(llm_with_tools, messages)
    except (TimeoutException, Exception) as e:
        llm_failed = True
        logger.warning("[router] LLM failed: %s, keyword fallback", str(e))

    router_duration = time.time() - router_start

    if not llm_failed and response and response.tool_calls:
        selected_skills = [tc["name"] for tc in response.tool_calls]
        first_params = response.tool_calls[0]["args"]

        # Cross-validation: LLM vs keyword scores
        kw_scores = _keyword_scores(user_input)
        llm_top = selected_skills[0]
        if kw_scores:
            kw_top = max(kw_scores, key=kw_scores.get)
            kw_conf = kw_scores[kw_top]
            if llm_top != kw_top and kw_conf >= 2:
                logger.info(
                    "[router] cross-validate: LLM=%s -> kw=%s (conf=%d)"
                    % (llm_top, kw_top, kw_conf)
                )
                selected_skills = [kw_top] + [s for s in selected_skills if s != kw_top]
                first_params = {"user_input": user_input}

        if "file_analysis_skill" in selected_skills and file_path and file_content:
            first_params["file_path"] = file_path
            first_params["file_content"] = file_content

        state["tool_result"] = {"skill": selected_skills[0], **first_params}
        state["skills_to_execute"] = selected_skills
        state["intent"] = selected_skills[0]
        logger.info(
            "[router] LLM selected %d skill(s) in %.2fs: %s"
            % (len(selected_skills), router_duration, "+".join(selected_skills))
        )
    else:
        fallback_skills = keyword_fallback(user_input)
        if fallback_skills:
            state["tool_result"] = {
                "skill": fallback_skills[0],
                "user_input": user_input,
            }
            state["skills_to_execute"] = fallback_skills
            state["intent"] = fallback_skills[0]
            logger.info(
                "[router] keyword fallback in %.2fs -> %s"
                % (router_duration, fallback_skills[0])
            )
        else:
            state["tool_result"] = {
                "skill": "unknown",
                "user_input": user_input,
                "data": "Unable to recognize the task, please rephrase.",
            }
            state["skills_to_execute"] = ["unknown"]
            state["intent"] = "unknown"
            logger.warning("[router] no match, intent=unknown")

    if response and hasattr(response, "response_metadata") and response.response_metadata:
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