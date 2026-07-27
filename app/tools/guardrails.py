import logging

logger = logging.getLogger("guardrails")

# Sensitive keywords that should be blocked
BLOCKED_KEYWORDS = ['政治', '政府', '颉覆', '反动', '爆炸', '杀人', '毒品', '武器', '赌博', '诈骗', '盗版', '黑客']

# Topics that should be redirected (not blocked, just guided)
REDIRECT_KEYWORDS = ['看病', '医疗', '股票', '基金']


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

    input_lower = user_input.lower()

    # Check blocked keywords
    for keyword in BLOCKED_KEYWORDS:
        if keyword in input_lower:
            logger.warning("[Guardrails] 检测到敏感词: %s, 已拦截", keyword)
            return {
                "safe": False,
                "action": "block",
                "message": (
                    "我是电商运营助手,"
                    "关于" + keyword + "建议咨询"
                    "相关专业渠道."
                    "您可以问我电商运营的任何问题."
                ),
            }

    # Check redirect keywords
    for keyword in REDIRECT_KEYWORDS:
        if keyword in input_lower:
            logger.info("[Guardrails] Off-topic detected: %s, redirecting", keyword)
            return {
                "safe": True,
                "action": "redirect",
                "message": (
                    "我是电商运营助手,"
                    "关于" + keyword + "建议咨询相关专业渠道."
                    "您可以问我电商运营的任何问题."
                ),
            }

    return {"safe": True, "action": "allow", "message": None}
