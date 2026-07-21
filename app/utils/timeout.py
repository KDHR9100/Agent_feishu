import functools
import signal
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError

logger = logging.getLogger("timeout")


class TimeoutException(Exception):
    pass


def timeout(seconds=30, error_message="Function call timed out"):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            executor = ThreadPoolExecutor(max_workers=1)
            future = executor.submit(func, *args, **kwargs)
            try:
                return future.result(timeout=seconds)
            except TimeoutError:
                logger.error("[Timeout] Function %s timed out after %d seconds" % (func.__name__, seconds))
                raise TimeoutException(error_message)
            finally:
                executor.shutdown(wait=False)
        return wrapper
    return decorator


def async_timeout(seconds=30, error_message="Async function call timed out"):
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            import asyncio
            loop = asyncio.get_event_loop()
            executor = ThreadPoolExecutor(max_workers=1)
            try:
                return await asyncio.wait_for(
                    loop.run_in_executor(executor, functools.partial(func, *args, **kwargs)),
                    timeout=seconds
                )
            except asyncio.TimeoutError:
                logger.error("[Timeout] Async function %s timed out after %d seconds" % (func.__name__, seconds))
                raise TimeoutException(error_message)
            finally:
                executor.shutdown(wait=False)
        return wrapper
    return decorator