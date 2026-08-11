"""
LLM 调用错误恢复层 (s11)

错误分类与恢复策略:
1. 上下文超限 -> 调用 on_context_overflow 回调裁剪后重试 (一次)
2. 限流/过载 (429/529) -> 指数退避 + 抖动重试
3. 其他异常 -> 切换备用模型重试 (一次), 仍失败则抛出

解耦设计: 不依赖 workflow/local_memory, 通过回调解耦
"""
import time
import random
import logging

logger = logging.getLogger("llm_retry")

MAX_RATE_LIMIT_RETRIES = 3
BASE_BACKOFF = 1.0
MAX_BACKOFF = 16.0
JITTER_RATIO = 0.3


def classify_error(exc) -> str:
    msg = str(exc).lower()
    if any(k in msg for k in ("429", "529", "rate limit", "rate_limit",
                              "overloaded", "too many requests")):
        return "rate_limit"
    if any(k in msg for k in ("context_length", "prompt_too_long",
                              "maximum context", "context window")):
        return "context_overflow"
    if "timeout" in msg or "timed out" in msg:
        return "timeout"
    return "other"


def _exponential_backoff(attempt: int) -> float:
    delay = min(BASE_BACKOFF * (2 ** attempt), MAX_BACKOFF)
    jitter = random.uniform(0, delay * JITTER_RATIO)
    return delay + jitter


def invoke_with_recovery(
    llm, messages, *,
    on_context_overflow=None,
    fallback_llm=None,
    max_rate_limit_retries=MAX_RATE_LIMIT_RETRIES,
):
    """
    带错误恢复的 LLM 调用

    恢复策略 (按顺序):
    1. 上下文超限 -> 压缩后重试 (一次)
    2. 限流/过载 -> 指数退避+抖动重试
    3. 其他错误 -> 切换备用模型 (一次)
    4. 全部耗尽 -> 抛出最后异常
    """
    current_llm = llm
    current_messages = list(messages)
    rate_limit_attempts = 0
    compacted = False
    switched_to_fallback = False

    while True:
        try:
            return current_llm.invoke(current_messages)
        except Exception as exc:
            err_type = classify_error(exc)

            # 1. 上下文超限 -> 压缩后重试
            if (err_type == "context_overflow"
                    and on_context_overflow is not None
                    and not compacted):
                logger.warning(
                    "[llm_retry] context overflow, compacting messages (len=%d)",
                    len(current_messages),
                )
                try:
                    current_messages = on_context_overflow(current_messages)
                    compacted = True
                    continue
                except Exception as compact_exc:
                    logger.error("[llm_retry] compaction failed: %s", compact_exc)

            # 2. 限流/过载 -> 退避重试
            if err_type == "rate_limit" and rate_limit_attempts < max_rate_limit_retries:
                delay = _exponential_backoff(rate_limit_attempts)
                logger.warning(
                    "[llm_retry] rate limit (attempt %d/%d), backoff %.1fs",
                    rate_limit_attempts + 1, max_rate_limit_retries, delay,
                )
                time.sleep(delay)
                rate_limit_attempts += 1
                continue

            # 3. 其他错误 -> 切换备用模型
            if fallback_llm is not None and not switched_to_fallback:
                logger.warning(
                    "[llm_retry] %s error, switching to fallback model", err_type,
                )
                current_llm = fallback_llm
                switched_to_fallback = True
                continue

            # 4. 全部恢复策略耗尽
            raise
