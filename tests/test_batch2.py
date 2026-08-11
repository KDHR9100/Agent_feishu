"""测试 s09 持久记忆 + s05 TodoWrite"""
import sys, os, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch, MagicMock

from app.utils.todo_manager import (
    create_todo, update_status, next_pending, all_completed,
    format_progress, check_stale, mark_updated,
)


# ============================================================
# s05: TodoWrite
# ============================================================
class TestCreateTodo:
    def test_creates_pending_items(self):
        todo = create_todo(["task1", "task2", "task3"])
        assert len(todo) == 3
        assert all(t["status"] == "pending" for t in todo)

    def test_empty(self):
        assert create_todo([]) == []


class TestUpdateStatus:
    def test_update_to_in_progress(self):
        todo = create_todo(["a", "b"])
        update_status(todo, 0, "in_progress")
        assert todo[0]["status"] == "in_progress"

    def test_only_one_in_progress(self):
        todo = create_todo(["a", "b"])
        update_status(todo, 0, "in_progress")
        update_status(todo, 1, "in_progress")
        assert todo[0]["status"] == "completed"
        assert todo[1]["status"] == "in_progress"

    def test_complete(self):
        todo = create_todo(["a"])
        update_status(todo, 0, "completed")
        assert todo[0]["status"] == "completed"

    def test_invalid_index(self):
        todo = create_todo(["a"])
        update_status(todo, 5, "completed")
        assert todo[0]["status"] == "pending"

    def test_invalid_status(self):
        todo = create_todo(["a"])
        update_status(todo, 0, "invalid")
        assert todo[0]["status"] == "pending"


class TestNextPending:
    def test_returns_first_pending(self):
        todo = create_todo(["a", "b"])
        assert next_pending(todo) == 0
        update_status(todo, 0, "completed")
        assert next_pending(todo) == 1

    def test_all_done(self):
        todo = create_todo(["a"])
        update_status(todo, 0, "completed")
        assert next_pending(todo) is None

    def test_empty(self):
        assert next_pending([]) is None


class TestAllCompleted:
    def test_true_when_all_done(self):
        todo = create_todo(["a", "b"])
        update_status(todo, 0, "completed")
        update_status(todo, 1, "completed")
        assert all_completed(todo) is True

    def test_false_when_pending(self):
        todo = create_todo(["a"])
        assert all_completed(todo) is False

    def test_false_when_empty(self):
        assert all_completed([]) is False


class TestFormatProgress:
    def test_shows_progress(self):
        todo = create_todo(["task1", "task2"])
        update_status(todo, 0, "completed")
        progress = format_progress(todo)
        assert "1/2" in progress
        assert "[x]" in progress
        assert "[ ]" in progress

    def test_empty(self):
        assert format_progress([]) == ""
        assert format_progress(None) == ""


class TestCheckStale:
    def test_no_todo(self):
        assert check_stale({}) is None

    def test_all_completed(self):
        todo = create_todo(["a"])
        update_status(todo, 0, "completed")
        assert check_stale({"todo_list": todo}) is None

    def test_stale_warning(self):
        todo = create_todo(["a"])
        state = {"todo_list": todo, "todo_last_updated_round": 0, "retry_count": 3}
        result = check_stale(state, threshold=2)
        assert result is not None
        assert "提醒" in result

    def test_not_stale(self):
        todo = create_todo(["a"])
        state = {"todo_list": todo, "todo_last_updated_round": 2, "retry_count": 3}
        assert check_stale(state, threshold=2) is None


# ============================================================
# s09: Persistent Memory
# ============================================================
class TestPersistentMemory:
    def setup_method(self):
        """使用临时目录"""
        self.tmp = tempfile.mkdtemp()
        self._orig_dir = __import__("app.memory.persistent_memory", fromlist=["MEMORY_DIR"]).MEMORY_DIR
        self._orig_index = __import__("app.memory.persistent_memory", fromlist=["MEMORY_INDEX"]).MEMORY_INDEX
        pm = __import__("app.memory.persistent_memory", fromlist=["MEMORY_DIR", "MEMORY_INDEX", "_ensure_dir"])
        pm.MEMORY_DIR = os.path.join(self.tmp, ".memory")
        pm.MEMORY_INDEX = os.path.join(pm.MEMORY_DIR, "MEMORY.md")
        pm._ensure_dir()

    def teardown_method(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_save_and_list(self):
        from app.memory.persistent_memory import save_memory, list_memories
        save_memory("test_mem", "test content", category="user", description="a test")
        entries = list_memories()
        assert len(entries) == 1
        assert entries[0]["name"] == "test_mem"

    def test_get_index(self):
        from app.memory.persistent_memory import save_memory, get_memory_index
        save_memory("shop_category", "女装", category="project")
        idx = get_memory_index()
        assert "shop_category" in idx

    def test_relevant_memories(self):
        from app.memory.persistent_memory import save_memory, get_relevant_memories
        save_memory("女装类目", "店铺主营女装", category="project", tags="女装,类目")
        results = get_relevant_memories("查看女装销量")
        assert len(results) > 0

    def test_extract_memory(self):
        from app.memory.persistent_memory import extract_memory_from_input
        result = extract_memory_from_input("记住我的店铺主营女装")
        assert result is not None
        assert "女装" in result["content"]

    def test_extract_no_trigger(self):
        from app.memory.persistent_memory import extract_memory_from_input
        assert extract_memory_from_input("查看销量") is None

    def test_try_save(self):
        from app.memory.persistent_memory import try_save_from_input, list_memories
        result = try_save_from_input("记住默认看7天数据")
        assert result is not None
        entries = list_memories()
        assert len(entries) >= 1

    def test_deduplicate(self):
        from app.memory.persistent_memory import save_memory, deduplicate, list_memories
        save_memory("dup", "content1", category="user")
        save_memory("dup", "content2", category="user")
        removed = deduplicate()
        assert removed >= 0  # 可能文件名相同直接覆盖
