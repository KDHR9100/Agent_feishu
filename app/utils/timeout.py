import functools
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError

# token attribution context propagation (thread-local does not inherit into pool threads)
from app.utils.token_tracker import snapshot as _tracker_snapshot
from app.utils.token_tracker import restore as _tracker_restore

logger = logging.getLogger("timeout")

# 共享线程池: 避免每次超时调用都创建/销毁 ThreadPoolExecutor 的开销
# (路由/技能链路每请求会多次经过超时装饰器, 逐次建池的线程开销不可忽略)
_SHARED_EXECUTOR = ThreadPoolExecutor(max_workers=32, thread_name_prefix="timeout-guard")


class TimeoutException(Exception):
    pass


def timeout(seconds=30, error_message="Function call timed out"):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            ctx = _tracker_snapshot()

            def _run():
                _tracker_restore(ctx)
                return func(*args, **kwargs)

            future = _SHARED_EXECUTOR.submit(_run)
            try:
                return future.result(timeout=seconds)
            except TimeoutError:
                logger.error(
                    "[Timeout] Function %s timed out after %d seconds"
                    % (func.__name__, seconds)
                )
                raise TimeoutException(error_message)

        return wrapper

    return decorator


def async_timeout(seconds=30, error_message="Async function call timed out"):
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            import asyncio

            loop = asyncio.get_event_loop()
            ctx = _tracker_snapshot()

            def _run():
                _tracker_restore(ctx)
                return func(*args, **kwargs)

            try:
                return await asyncio.wait_for(
                    loop.run_in_executor(_SHARED_EXECUTOR, _run),
                    timeout=seconds,
                )
            except asyncio.TimeoutError:
                logger.error(
                    "[Timeout] Async function %s timed out after %d seconds"
                    % (func.__name__, seconds)
                )
                raise TimeoutException(error_message)

        return wrapper

    return decorator
