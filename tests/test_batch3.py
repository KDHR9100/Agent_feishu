"""测试 s04 Hooks + s13 Background Tasks"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import MagicMock, patch

from app.utils.hooks import (
    register_hook, unregister_hook, trigger_hooks, clear_hooks, list_hooks,
)
from app.utils.background_tasks import (
    run_background, get_task_status, list_running_tasks, cleanup_completed,
)


# ============================================================
# s04: Hooks
# ============================================================
class TestHookRegistry:
    def setup_method(self):
        clear_hooks()

    def teardown_method(self):
        clear_hooks()

    def test_register_and_trigger(self):
        called = []
        register_hook("UserPromptSubmit", lambda ctx: called.append(ctx["user_input"]))
        trigger_hooks("UserPromptSubmit", {"user_input": "hello"})
        assert called == ["hello"]

    def test_multiple_handlers(self):
        results = []
        register_hook("PreToolUse", lambda ctx: results.append("a"))
        register_hook("PreToolUse", lambda ctx: results.append("b"))
        trigger_hooks("PreToolUse", {})
        assert results == ["a", "b"]

    def test_handler_can_modify_context(self):
        register_hook("PostToolUse", lambda ctx: {"modified": True})
        ctx = trigger_hooks("PostToolUse", {"original": 1})
        assert ctx["original"] == 1
        assert ctx["modified"] is True

    def test_handler_error_doesnt_crash(self):
        register_hook("Stop", lambda ctx: (_ for _ in ()).throw(ValueError("boom")))
        # Should not raise
        trigger_hooks("Stop", {})
        # Other handlers still run
        called = []
        register_hook("Stop", lambda ctx: called.append("ok"))
        trigger_hooks("Stop", {})
        assert called == ["ok"]

    def test_unregister(self):
        h = lambda ctx: None
        register_hook("UserPromptSubmit", h)
        unregister_hook("UserPromptSubmit", h)
        assert len(list_hooks("UserPromptSubmit")["UserPromptSubmit"]) == 0

    def test_unknown_event_ignored(self):
        register_hook("UnknownEvent", lambda ctx: None)
        # Should not raise
        trigger_hooks("UnknownEvent", {})

    def test_clear_all(self):
        register_hook("UserPromptSubmit", lambda ctx: None)
        register_hook("PreToolUse", lambda ctx: None)
        clear_hooks()
        hooks = list_hooks()
        assert all(len(v) == 0 for v in hooks.values())


class TestHookEvents:
    def setup_method(self):
        clear_hooks()

    def teardown_method(self):
        clear_hooks()

    def test_all_four_events_exist(self):
        from app.utils.hooks import EVENTS
        assert "UserPromptSubmit" in EVENTS
        assert "PreToolUse" in EVENTS
        assert "PostToolUse" in EVENTS
        assert "Stop" in EVENTS


# ============================================================
# s13: Background Tasks
# ============================================================
class TestBackgroundTasks:
    def test_run_and_complete(self):
        def slow_task(x):
            return x * 2

        task_id = run_background(slow_task, args=(21,), description="test double")
        time.sleep(0.5)  # wait for completion
        status = get_task_status(task_id)
        assert status is not None
        assert status["status"] == "completed"
        assert status["result"] == 42

    def test_on_complete_callback(self):
        results = []
        def task():
            return "done"

        def on_complete(task_id, result, error):
            results.append((task_id, result, error))

        task_id = run_background(task, on_complete=on_complete, description="cb test")
        time.sleep(0.5)
        assert len(results) == 1
        assert results[0][1] == "done"
        assert results[0][2] is None

    def test_failed_task(self):
        def fail_task():
            raise ValueError("intentional failure")

        task_id = run_background(fail_task, description="fail test")
        time.sleep(0.5)
        status = get_task_status(task_id)
        assert status["status"] == "failed"
        assert "intentional" in status["error"]

    def test_on_complete_with_error(self):
        results = []
        def fail():
            raise RuntimeError("boom")

        run_background(fail, on_complete=lambda tid, r, e: results.append((r, e)))
        time.sleep(0.5)
        assert len(results) == 1
        assert results[0][0] is None
        assert "boom" in results[0][1]

    def test_list_running(self):
        import time as _t
        def slow():
            _t.sleep(1)

        tid = run_background(slow, description="slow test")
        running = list_running_tasks()
        assert any(t["task_id"] == tid for t in running)
        time.sleep(1.5)  # cleanup
        assert not any(t["task_id"] == tid for t in list_running_tasks())

    def test_cleanup(self):
        def quick():
            return 1

        for i in range(5):
            run_background(quick, description="cleanup test %d" % i)
        time.sleep(0.5)
        cleanup_completed(max_keep=2)
        # Should have kept only 2 completed tasks
        from app.utils.background_tasks import _tasks
        assert len(_tasks) <= 2

    def test_default_callback_creator(self):
        from app.utils.background_tasks import default_complete_callback
        cb = default_complete_callback("test_conv")
        assert callable(cb)
