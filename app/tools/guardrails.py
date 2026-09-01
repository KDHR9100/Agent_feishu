# -*- coding: utf-8 -*-
"""输入安全护栏: 关键词快筛 + LLM 二次确认 (P7)

- 关键词命中只作为"嫌疑信号", 由 LLM 二次确认决定最终裁决,
  避免 "爆款/爆单/防诈骗指南" 等业务语境被纯子串匹配误杀。
- LLM 不可用/超时/解析失败时, 回退到关键词裁决 (fail-safe, 行为与旧版一致)。
- 业务比喻白名单先行剥离 (杀人价/像股票一样等), 降级模式下不误杀业务黑话。
- 返回契约不变: {"safe": bool, "action": allow/block/redirect, "message": str|None}
"""
import logging
import re

import requests

from app.config import config

logger = logging.getLogger("guardrails")

# Sensitive keywords that should be blocked
BLOCKED_KEYWORDS = ['政治', '政府', '颠覆', '反动', '爆炸', '杀人', '毒品', '武器', '赌博', '诈骗', '盗版', '黑客']

# 电商业务比喻白名单: 高置信口语/比喻句式, 剥离后再做关键词匹配。
# 动机: LLM 二次确认不可用(降级模式)时, 裸关键词裁决会把 "杀人价"(价格战口语)、
# "像股票一样有没有行情"(比喻句式) 误判为 block/redirect。剥离后:
# - 降级模式: 不再误杀业务黑话
# - 健康模式: 无关键词命中则直接放行, 还省一次 LLM 确认调用
# 注意: 仅匹配"敏感词作为比喻成分"的固定句式, "我要杀人"这类真实危险请求不受影响。
_IDIOM_PATTERNS = [
    re.compile(r"杀人价"),                                    # 价格战口语: "简直是杀人价"
    re.compile(r"像(股票|基金|看病|医疗|赌博|爆炸|毒品)[^，。？！\n]{0,6}一样"),  # 比喻句式: "像股票一样"
]


def _strip_idioms(text: str) -> str:
    """剥离业务比喻用语, 避免比喻成分触发关键词误杀"""
    for pat in _IDIOM_PATTERNS:
        text = pat.sub("", text)
    return text

# Topics that should be redirected (not blocked, just guided)
REDIRECT_KEYWORDS = [
    '看病', '医疗', '股票', '基金',
    # P7 扩充: 医疗/用药口语
    '吃药', '用药', '买药', '开药', '什么药', '哪种药', '处方', '挂号', '诊断', '偏方', '治病',
    # P7 扩充: 金融投资
    '炒股', '理财', '期货', '外汇', '比特币', '加密货币', '荐股',
]

_REVIEW_TIMEOUT = 10.0

_REVIEW_SYSTEM_PROMPT = (
    "你是电商运营助手的输入安全审查员。请判断用户消息属于哪一类:\n"
    "- block: 涉政/暴力/毒品/赌博/诈骗等违法违规或危险内容(用户真的在寻求这类帮助)\n"
    "- redirect: 医疗健康(看病/用药/诊断)或金融投资(炒股/理财/期货)等电商域外求助\n"
    "- allow: 正常电商运营内容; 敏感词只是商业比喻、商品类目或正常词汇的一部分时也算 allow\n"
    "  (例如 \"爆款\"\"爆单\"\"防诈骗提醒\"\"政府补贴类目\" 都不是真正的敏感请求;\n"
    "   商家咨询 \"被职业打假人/恶意投诉/敲诈勒索怎么应对\" 属于电商经营问题, 判 allow)\n"
    "只输出一个单词: allow / block / redirect, 不要输出任何其他内容。"
)


def _record_review_usage(resp_json):
    """裸 requests 调用不经 LangChain 回调, 手工记账 token 消耗 (失败静默, 不影响裁决)"""
    try:
        usage = (resp_json or {}).get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)
        if input_tokens <= 0 and output_tokens <= 0:
            return
        from app.monitoring import monitoring_stats

        monitoring_stats.record_token_usage(
            skill_name="guardrails",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            conversation_id="",
        )
    except Exception:
        pass


def _llm_review(user_input: str):
    """LLM 二次确认, 返回 allow/block/redirect; 任何异常返回 None (由调用方回退关键词裁决)"""
    try:
        if not config.LLM_API_KEY or not config.LLM_API_BASE:
            return None
        resp = requests.post(
            config.LLM_API_BASE.rstrip("/") + "/chat/completions",
            headers={
                "Authorization": "Bearer %s" % config.LLM_API_KEY,
                "Content-Type": "application/json",
            },
            json={
                "model": config.LLM_MODEL_NAME,
                "temperature": 0,
                "max_tokens": 8,
                "enable_thinking": False,
                "messages": [
                    {"role": "system", "content": _REVIEW_SYSTEM_PROMPT},
                    {"role": "user", "content": user_input[:500]},
                ],
            },
            timeout=_REVIEW_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.warning(
                "[Guardrails] LLM review HTTP %s, fallback to keyword verdict", resp.status_code)
            return None
        body = resp.json()
        _record_review_usage(body)
        content = (body["choices"][0]["message"]["content"] or "").strip().lower()
        for verdict in ("block", "redirect", "allow"):
            if verdict in content:
                return verdict
        logger.warning("[Guardrails] LLM review unparsable: %r, fallback", content[:80])
        return None
    except Exception as e:
        logger.warning("[Guardrails] LLM review failed: %s, fallback to keyword verdict", e)
        return None


def check_input(user_input: str) -> dict:
    """
    输入安全检测: 护栏
    Returns dict with:
    - "safe": bool, whether input is safe to process
    - "action": "allow", "block", or "redirect"
    - "message": response message if blocked/redirected, None if allowed
    """
    if not user_input or not user_input.strip():
        return {"safe": True, "action": "allow", "message": None}

    input_lower = _strip_idioms(user_input).lower()

    # Check blocked keywords
    hit_keyword, hit_type = None, None
    for keyword in BLOCKED_KEYWORDS:
        if keyword in input_lower:
            hit_keyword, hit_type = keyword, "block"
            break
    if hit_keyword is None:
        for keyword in REDIRECT_KEYWORDS:
            if keyword in input_lower:
                hit_keyword, hit_type = keyword, "redirect"
                break

    if hit_keyword is None:
        return {"safe": True, "action": "allow", "message": None}

    # P7: 关键词命中后 LLM 二次确认; 失败回退关键词裁决 (fail-safe)
    verdict = _llm_review(user_input) or hit_type
    logger.info(
        "[Guardrails] keyword=%s kw_verdict=%s final_verdict=%s",
        hit_keyword, hit_type, verdict)

    if verdict == "allow":
        return {"safe": True, "action": "allow", "message": None}

    if verdict == "block":
        logger.warning("[Guardrails] 检测到敏感词: %s, 已拦截", hit_keyword)
        return {
            "safe": False,
            "action": "block",
            "message": (
                "我是电商运营助手,"
                "关于" + hit_keyword + "建议咨询"
                "相关专业渠道."
                "您可以问我电商运营的任何问题."
            ),
        }

    # redirect
    logger.info("[Guardrails] Off-topic detected: %s, redirecting", hit_keyword)
    return {
        "safe": True,
        "action": "redirect",
        "message": (
            "我是电商运营助手,"
            "关于" + hit_keyword + "建议咨询相关专业渠道."
            "您可以问我电商运营的任何问题."
        ),
    }
