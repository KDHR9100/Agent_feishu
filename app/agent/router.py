import hashlib
import logging
import os
import threading
import time
from collections import OrderedDict
from langchain_core.tools import StructuredTool
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_router_llm
from app.prompts import ROUTER_PROMPT
from app.utils.timeout import timeout, TimeoutException
from app.mcp_server import skill_registry
from app.utils.security import detect_injection, SAFE_BLOCK_RESPONSE, wrap_untrusted
from app.utils.token_tracker import track_as

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


def _build_skill_list_section() -> str:
    """从 manifest 动态生成路由 prompt 的技能清单段落。

    与 _build_tools 同源: prompt 里描述的技能与 bind_tools 注入的工具
    永远一致, manifest 增删技能后无需手改 prompt。
    """
    lines = []
    for i, s in enumerate(skill_registry.list_tools(), 1):
        lines.append("%d. %s：%s" % (i, s["name"], s["description"]))
    return (
        "## 技能清单（系统自动同步，与你可调用的工具完全一致）\n"
        + "\n".join(lines)
    )


# 关键词快速路径开关: 高置信唯一命中时跳过 LLM, 路由耗时≈0ms
# 默认关闭: 意图识别以路由 LLM 为主, 关键词仅在 LLM 失败时兜底;
# 需要极致响应速度时可设 ROUTER_KEYWORD_FAST_PATH=true 重新启用
KEYWORD_FAST_PATH = os.getenv("ROUTER_KEYWORD_FAST_PATH", "false").lower() == "true"
# 快速路径触发阈值: 与交叉验证的 conf>=2 保持一致的置信度语义
KEYWORD_FAST_PATH_MIN_CONF = int(os.getenv("ROUTER_KEYWORD_FAST_PATH_MIN_CONF", "2"))
# 关键词覆盖/补充 LLM 结果开关: 默认关闭, 路由结果完全由路由 LLM 决定;
# 关键词仅在 LLM 调用失败/超时时作为兜底(见 route() 尾部)
KEYWORD_OVERRIDE_LLM = os.getenv("ROUTER_KEYWORD_OVERRIDE", "false").lower() == "true"

# 路由结果缓存: temperature=0 下路由结果确定, 相同输入+相同会话上下文直接复用,
# 免去飞书 webhook 重复推送/用户重发同一问题时的 LLM 调用
ROUTER_CACHE_ENABLED = os.getenv("ROUTER_CACHE_ENABLED", "true").lower() == "true"
ROUTER_CACHE_TTL = float(os.getenv("ROUTER_CACHE_TTL", "600"))
ROUTER_CACHE_MAXSIZE = int(os.getenv("ROUTER_CACHE_MAXSIZE", "512"))

_router_cache = OrderedDict()
_router_cache_lock = threading.Lock()


def _cache_key(user_input, has_file, history_text):
    # registry 版本入 key: manifest 热更新后旧缓存自动失效
    hist_fp = hashlib.sha1(history_text.encode("utf-8")).hexdigest()[:16] if history_text else ""
    return (user_input.strip(), bool(has_file), skill_registry.version, hist_fp)


def _cache_get(key):
    if not ROUTER_CACHE_ENABLED:
        return None
    with _router_cache_lock:
        item = _router_cache.get(key)
        if not item:
            return None
        ts, skills = item
        if time.time() - ts > ROUTER_CACHE_TTL:
            _router_cache.pop(key, None)
            return None
        _router_cache.move_to_end(key)
        return list(skills)


def _cache_put(key, skills):
    if not ROUTER_CACHE_ENABLED:
        return
    with _router_cache_lock:
        _router_cache[key] = (time.time(), list(skills))
        _router_cache.move_to_end(key)
        while len(_router_cache) > ROUTER_CACHE_MAXSIZE:
            _router_cache.popitem(last=False)

# ============================================================
# 热插拔缓存: 按 registry 版本号驱动, manifest 变化时自动重建
# ============================================================
KEYWORD_RULES = skill_registry.get_keyword_rules()

_cache = {
    "version": -1,          # 与 registry.version 对比, 不一致则重建
    "tools": None,          # StructuredTool 列表
    "llm_with_tools": None,  # bind_tools 后的 LLM
    "skill_section": "",    # 路由 prompt 的动态技能清单段落
}


def _ensure_tools_fresh():
    """每次路由前检查 manifest 是否变化; 有变化则重建工具列表与关键词表"""
    global KEYWORD_RULES
    skill_registry.reload_if_changed()
    ver = skill_registry.version
    if _cache["version"] != ver:
        _cache["tools"] = _build_tools()
        _cache["skill_section"] = _build_skill_list_section()
        KEYWORD_RULES = skill_registry.get_keyword_rules()
        _cache["llm_with_tools"] = None  # 使 bind_tools 缓存失效
        _cache["version"] = ver
        logger.info(
            "[router] hot-reload: registry version=%d, skills=%d",
            ver, skill_registry.skill_count,
        )


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


def _get_llm_with_tools():
    if _cache["llm_with_tools"] is None:
        _llm = get_router_llm()
        _cache["llm_with_tools"] = _llm.bind_tools(_cache["tools"])
    return _cache["llm_with_tools"]


@timeout(20)
def _router_llm_call(llm_with_tools, messages):
    """带超时保护的路由 LLM 调用"""
    return llm_with_tools.invoke(messages)


def router(state):
    # 热插拔: 先检查 manifest 变化 (新增技能无需重启即可路由命中)
    _ensure_tools_fresh()
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
            # 路由只需要上下文线索, 截断长消息控制路由 prompt 体积(降低 LLM 首 token 延迟)
            content = str(msg.get("content", ""))[:200]
            if role == "user":
                history_lines.append(f"用户: {content}")
            elif role == "assistant":
                history_lines.append(f"助手: {content}")
        history_text = "\n".join(history_lines)

    # 技能清单段落由 manifest 动态生成注入, 与 bind_tools 的工具列表同源,
    # 保证 prompt 描述与实际可调用工具永远一致 (无需手工维护两份清单)
    enhanced_prompt = ROUTER_PROMPT + "\n\n" + _cache["skill_section"]
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

    # ── 关键词快速路径: 高置信唯一命中时跳过 LLM, 路由耗时≈0ms ──
    # 语义与交叉验证一致(conf>=2 时关键词本就会覆盖 LLM 结果), 故可直接省去 LLM 调用;
    # 反思重试轮(带 reflect_feedback)不走快速路径, 交给 LLM 结合反馈重新判断
    if KEYWORD_FAST_PATH and not reflect_feedback:
        kw_scores = _keyword_scores(user_input)
        if kw_scores:
            sorted_kw = sorted(kw_scores.items(), key=lambda kv: kv[1], reverse=True)
            top_skill, top_conf = sorted_kw[0]
            tied_at_top = len(sorted_kw) > 1 and sorted_kw[1][1] == top_conf
            if top_conf >= KEYWORD_FAST_PATH_MIN_CONF and not tied_at_top:
                fast_start = time.time()
                selected_skills = [s for s, c in sorted_kw if c >= KEYWORD_FAST_PATH_MIN_CONF]
                first_params = {"user_input": user_input}
                if "file_analysis_skill" in selected_skills and file_path:
                    first_params["file_path"] = file_path
                    first_params["file_content"] = file_content
                state["tool_result"] = {"skill": selected_skills[0], **first_params}
                state["skills_to_execute"] = selected_skills
                state["intent"] = selected_skills[0]
                logger.info(
                    "[router] keyword fast path in %.2fs -> %s (top=%s conf=%d)"
                    % (time.time() - fast_start, selected_skills, top_skill, top_conf)
                )
                return state

    # ── 路由缓存: temperature=0 结果确定, 相同输入+相同上下文直接复用, 省去一次 LLM 调用 ──
    cache_key = _cache_key(user_input, file_path, history_text)
    cached_skills = None if reflect_feedback else _cache_get(cache_key)
    if cached_skills:
        first_params = {"user_input": user_input}
        if "file_analysis_skill" in cached_skills and file_path:
            first_params["file_path"] = file_path
            first_params["file_content"] = file_content
        state["tool_result"] = {"skill": cached_skills[0], **first_params}
        state["skills_to_execute"] = cached_skills
        state["intent"] = cached_skills[0]
        logger.info("[router] cache hit -> %s" % cached_skills)
        return state

    # LLM routing with timeout + keyword fallback
    logger.info("[router] calling LLM with tools...")
    router_start = time.time()
    response = None
    llm_failed = False

    try:
        llm_with_tools = _get_llm_with_tools()
        # 归属标签: 本次 LLM 调用的 token 记入 "router"
        with track_as("router", state.get("conversation_id", "")):
            response = _router_llm_call(llm_with_tools, messages)
    except (TimeoutException, Exception) as e:
        llm_failed = True
        logger.warning("[router] LLM failed: %s, keyword fallback", str(e))

    router_duration = time.time() - router_start

    if not llm_failed and response and response.tool_calls:
        selected_skills = [tc["name"] for tc in response.tool_calls]
        first_params = response.tool_calls[0]["args"]

        # Cross-validation: LLM vs keyword scores
        # 默认关闭(意图识别以路由 LLM 为准), 需设 ROUTER_KEYWORD_OVERRIDE=true 才启用
        kw_scores = _keyword_scores(user_input) if KEYWORD_OVERRIDE_LLM else {}
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
        # 路由结果确定(temperature=0): 写入缓存供重复请求复用 (反思重试轮不写缓存)
        if not reflect_feedback:
            _cache_put(cache_key, selected_skills)
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