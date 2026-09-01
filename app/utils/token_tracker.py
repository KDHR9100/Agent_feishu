"""LLM Token 归属追踪 (P0-3 修复)

原理:
- config.py 的 LLM 单例挂载 TokenTrackingHandler, 在每次 LLM 调用结束时
  (on_llm_end) 从响应中提取真实 token_usage, 按"当前归属标签"写入 SQLite。
- 归属标签保存在 thread-local 中, 由调用方 (router/planner/技能/answer)
  通过 track_as() 上下文管理器设置; @timeout 工具会把该上下文传播到工作线程。
- 这样技能内部的 LLM 调用无需改动即可被正确记账。
"""
import logging
import threading
from contextlib import contextmanager

from langchain_core.callbacks import BaseCallbackHandler

logger = logging.getLogger("token_tracker")

_tls = threading.local()


def set_context(owner=None, conversation_id=None):
    """设置当前线程的归属标签 / 会话 ID"""
    _tls.owner = owner
    if conversation_id is not None:
        _tls.conversation_id = conversation_id


def get_context():
    """返回 (owner, conversation_id)"""
    return getattr(_tls, "owner", None), getattr(_tls, "conversation_id", None)


def snapshot():
    """当前线程上下文快照 (供 @timeout 传播到工作线程)"""
    return dict(vars(_tls))


def restore(snap):
    """把上下文快照恢复到当前线程"""
    vars(_tls).clear()
    if snap:
        vars(_tls).update(snap)


@contextmanager
def track_as(owner, conversation_id=None):
    """上下文管理器: 标记块内所有 LLM 调用的归属标签, 退出后还原"""
    prev_owner, prev_conv = get_context()
    set_context(owner, conversation_id)
    try:
        yield
    finally:
        set_context(prev_owner, prev_conv)


def _extract_token_usage(response):
    """从 LLMResult 中提取 token 用量, 返回 (input_tokens, output_tokens)"""
    usage = {}
    llm_output = getattr(response, "llm_output", None) or {}
    usage = llm_output.get("token_usage") or llm_output.get("usage") or {}
    if not usage:
        # 兜底: 部分版本 token_usage 位于 generation 的 response_metadata 中
        for gen_list in getattr(response, "generations", None) or []:
            for gen in gen_list:
                info = getattr(gen, "generation_info", None) or {}
                meta = info.get("response_metadata") or {}
                usage = meta.get("token_usage") or meta.get("usage") or {}
                if usage:
                    break
            if usage:
                break
    input_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    output_tokens = int(
        usage.get("completion_tokens") or usage.get("output_tokens") or 0
    )
    return input_tokens, output_tokens


class TokenTrackingHandler(BaseCallbackHandler):
    """LangChain 回调: on_llm_end 时把真实 token 消耗按归属标签写入 SQLite"""

    # 记录失败不应影响主流程
    raise_error = False

    def on_llm_end(self, response, **kwargs):
        try:
            owner, conversation_id = get_context()
            if not owner:
                # 兜底归属: 未标记 track_as 的调用路径(闲聊兜底/记忆摘要/
                # 工具内直调等)不再静默丢弃, 保证记账总量与真实消耗一致
                owner = "unattributed"
            input_tokens, output_tokens = _extract_token_usage(response)
            if input_tokens <= 0 and output_tokens <= 0:
                return
            from app.monitoring import monitoring_stats

            monitoring_stats.record_token_usage(
                skill_name=owner,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                conversation_id=conversation_id or "",
            )
            logger.info(
                "[token_tracker] owner=%s prompt=%d completion=%d conversation=%s"
                % (owner, input_tokens, output_tokens, conversation_id)
            )
        except Exception as e:
            logger.debug("[token_tracker] record failed: %s" % e)
