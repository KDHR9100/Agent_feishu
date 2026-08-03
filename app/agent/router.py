import logging
import time
from langchain_core.tools import StructuredTool
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_router_llm
from app.prompts import ROUTER_PROMPT
from app.utils.timeout import timeout, TimeoutException
from app.mcp_server import skill_registry
from app.utils.security import detect_injection, SAFE_BLOCK_RESPONSE, wrap_untrusted

logger = logging.getLogger("router")


# ============================================================
# 动态工具定义: 从 skill_registry 生成 StructuredTool 列表
# ============================================================
def _build_tool_func(skill_name: str, description: str):
    """为每个技能动态生成 tool function"""
    def tool_func(user_input: str) -> dict:
        return {"skill": skill_name, "user_input": user_input}
    tool_func.__name__ = skill_name
    tool_func.__doc__ = description
    return tool_func


def _build_tools():
    """从 manifest 动态构建 StructuredTool 列表"""
    tool_list = []
    for skill_info in skill_registry.list_tools():
        func = _build_tool_func(skill_info["name"], skill_info["description"])
        tool_list.append(StructuredTool.from_function(func))
    logger.info("[router] built %d tools from manifest", len(tool_list))
    return tool_list


tools = _build_tools()

# ============================================================
# Keyword fallback: 从 manifest 动态加载(替代硬编码)
# ============================================================
KEYWORD_RULES = skill_registry.get_keyword_rules()


def _keyword_scores(user_input: str) -> dict:
    input_lower = user_input.lower()
    scores = {}
    for skill, keywords in KEYWORD_RULES.items():
        # 对命中关键词做大小写去重, 避免 'SKU'/'sku' 这类大小写变体
        # 被重复计数导致置信度虚高(进而触发交叉验证误覆盖)
        matched = {kw.lower() for kw in keywords if kw.lower() in input_lower}
        if matched:
            scores[skill] = len(matched)
    return scores


def keyword_fallback(user_input: str) -> list:
    """基于关键词匹配返回技能列表，无匹配时返回空列表。多技能命中时按得分降序返回。"""
    scores = _keyword_scores(user_input)
    if not scores:
        return []
    # 按得分降序返回所有命中的技能
    sorted_skills = sorted(scores, key=scores.get, reverse=True)
    logger.info("[router] keyword_fallback matched %d skill(s): %s", len(sorted_skills), sorted_skills)
    return sorted_skills


_llm_with_tools = None


def _get_llm_with_tools():
    global _llm_with_tools
    if _llm_with_tools is None:
        _llm = get_router_llm()
        _llm_with_tools = _llm.bind_tools(tools)
    return _llm_with_tools


@timeout(30)
def _router_llm_call(llm_with_tools, messages):
    """带超时保护的路由 LLM 调用"""
    return llm_with_tools.invoke(messages)


def router(state):
    user_input = state["user_input"]
    file_path = state.get("file_path")
    file_content = state.get("file_content")
    history = state.get("history", [])

    # ── 注入防护第一道防线: 路由入口拦截 ──
    # 必须在路由分发前检测, 防止注入指令被分发到合法技能
    # (如 inventory_skill) 从而绕过检测
    if detect_injection(user_input):
        logger.warning(
            "[router] INJECTION BLOCKED at routing stage | conversation_id=%s | "
            "input_len=%d | input_preview=%s"
            % (state.get("conversation_id", "?"), len(user_input), user_input[:100])
        )
        state["tool_result"] = {
            "skill": "unknown",
            "user_input": user_input,
            "data": SAFE_BLOCK_RESPONSE,
            "injection_blocked": True,
        }
        state["skills_to_execute"] = ["unknown"]
        state["intent"] = "injection_blocked"
        state["execution_plan"] = None
        return state

    # ── 间接注入防护: 上传文件内容同样是不可信输入 ──
    # 攻击者可上传含注入指令的文件/图片, 经 VLM 解析后进入 LLM 上下文
    if file_content and detect_injection(file_content):
        logger.warning(
            "[router] INJECTION in file_content SANITIZED | conversation_id=%s | file=%s | len=%d"
            % (state.get("conversation_id", "?"), file_path, len(file_content))
        )
        file_content = "[文件内容含可疑指令，已为安全拦截。请重新发送常规数据文件。]"
        state["file_content"] = file_content

    logger.info(
        "[router] user_input=%s, conversation_id=%s, has_file=%s"
        % (
            user_input[:80] + ("..." if len(user_input) > 80 else ""),
            state.get("conversation_id", "default"),
            bool(file_path),
        )
    )

    # 只要有 file_path 就走文件快捷路径，file_content 可能为 None（VLM 解析失败时）
    if file_path:
        if not file_content:
            file_content = "[文件已上传，待解析]"
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
                # 用分隔符包裹不可信文件内容, 降低间接注入风险
                "file_content": wrap_untrusted(file_content),
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

            # Multi-skill supplement: if keyword detects 2+ skills but LLM only returned 1
            # 仅补充关键词置信度>=2 的技能, 避免 conf=1 的弱关键词
            # 把无关技能误拉进来(如库存查询被'SKU'字样带入 product_skill)
            if len(kw_scores) >= 2 and len(selected_skills) == 1:
                sorted_kw = sorted(kw_scores, key=kw_scores.get, reverse=True)
                for kw_skill in sorted_kw:
                    if kw_skill not in selected_skills and kw_scores[kw_skill] >= 2:
                        selected_skills.append(kw_skill)
                first_params = {"user_input": user_input}
                logger.info(
                    "[router] multi-skill supplement: keyword detected %d skills, merged: %s"
                    % (len(selected_skills), selected_skills)
                )

        if "file_analysis_skill" in selected_skills and file_path:
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