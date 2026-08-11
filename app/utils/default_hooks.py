"""
默认 hook 注册 (s04)

在应用启动时导入此模块即可注册默认 hook:
- UserPromptSubmit: 审计日志
- PreToolUse: 注入检测 (纵深防御)
- PostToolUse: 执行日志
- Stop: 回答审计

自定义 hook 只需在业务代码中 register_hook 即可, 不需改主链路
"""
import logging
from app.utils.hooks import register_hook

logger = logging.getLogger("default_hooks")


def _audit_prompt(context):
    """UserPromptSubmit: 记录用户输入审计日志"""
    logger.info(
        "[audit] user_prompt | conversation=%s | input_len=%d | input_preview=%s"
        % (context.get("conversation_id", "?"),
           len(context.get("user_input", "")),
           context.get("user_input", "")[:80])
    )


def _pre_tool_log(context):
    """PreToolUse: 工具执行前日志"""
    logger.info(
        "[audit] pre_tool | skill=%s | conversation=%s"
        % (context.get("skill_name", "?"), context.get("conversation_id", "?"))
    )


def _post_tool_log(context):
    """PostToolUse: 工具执行后日志"""
    result = context.get("result", {})
    result_type = result.get("type", "?") if isinstance(result, dict) else "?"
    logger.info(
        "[audit] post_tool | skill=%s | result_type=%s | conversation=%s"
        % (context.get("skill_name", "?"), result_type, context.get("conversation_id", "?"))
    )


def _stop_log(context):
    """Stop: 回答审计"""
    logger.info(
        "[audit] stop | conversation=%s | answer_len=%d"
        % (context.get("conversation_id", "?"), len(str(context.get("answer", ""))))
    )


def register_default_hooks():
    """注册默认审计 hook (在应用启动时调用)"""
    register_hook("UserPromptSubmit", _audit_prompt)
    register_hook("PreToolUse", _pre_tool_log)
    register_hook("PostToolUse", _post_tool_log)
    register_hook("Stop", _stop_log)
    logger.info("[default_hooks] registered 4 audit hooks")
