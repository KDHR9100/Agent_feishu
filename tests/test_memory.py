"""测试会话记忆（内存 + SQLite 持久化）"""
import os, sys, pytest, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///./test_memory.db"

class TestLocalMemory:
    def setup_method(self):
        from app.memory.local_memory import LocalMemory
        self.memory = LocalMemory(max_history=5)
        self._cid = str(uuid.uuid4())[:8]

    def test_add_and_get_message(self):
        cid = self._cid + "_add"
        self.memory.add_message(cid, "user", "你好")
        self.memory.add_message(cid, "assistant", "你好，有什么可以帮你？")
        history = self.memory.get_history(cid)
        assert len(history) == 2
        assert history[0]["role"] == "user"

    def test_get_last_n_messages(self):
        for i in range(10):
            self.memory.add_message("conv2", "user", f"msg_{i}")
        last_3 = self.memory.get_last_n_messages("conv2", n=3)
        assert len(last_3) == 3
        assert last_3[0]["content"] == "msg_7"

    def test_max_history_trim(self):
        for i in range(10):
            self.memory.add_message("conv3", "user", f"msg_{i}")
        history = self.memory.get_history("conv3")
        assert len(history) <= 5

    def test_clear_history(self):
        self.memory.add_message("conv4", "user", "test")
        self.memory.clear_history("conv4")
        history = self.memory.get_history("conv4")
        assert len(history) == 0

    def test_empty_conversation(self):
        history = self.memory.get_history("nonexistent")
        assert history == []

    def test_multiple_conversations(self):
        cid_a = self._cid + "_a"
        cid_b = self._cid + "_b"
        self.memory.add_message(cid_a, "user", "hello_a")
        self.memory.add_message(cid_b, "user", "hello_b")
        assert len(self.memory.get_history(cid_a)) == 1
        assert len(self.memory.get_history(cid_b)) == 1

    def test_format_history(self):
        self.memory.add_message("conv5", "user", "问题")
        self.memory.add_message("conv5", "assistant", "回答")
        formatted = self.memory.format_history("conv5")
        assert "user: 问题" in formatted
        assert "assistant: 回答" in formatted




class TestMemoryLRU:
    def test_lru_eviction_on_max_conversations(self):
        """超过 max_conversations 时淘汰最久未使用的会话"""
        from app.memory.local_memory import LocalMemory
        mem = LocalMemory(max_history=10, max_conversations=3)
        mem.add_message("conv_1", "user", "hello 1")
        mem.add_message("conv_2", "user", "hello 2")
        mem.add_message("conv_3", "user", "hello 3")
        mem.add_message("conv_4", "user", "hello 4")
        # conv_1 should be evicted
        assert "conv_1" not in mem.conversations
        assert "conv_4" in mem.conversations

    def test_lru_touch_updates_order(self):
        """访问会话更新 LRU 顺序，不被淘汰"""
        from app.memory.local_memory import LocalMemory
        mem = LocalMemory(max_history=10, max_conversations=3)
        mem.add_message("conv_1", "user", "hello 1")
        mem.add_message("conv_2", "user", "hello 2")
        mem.add_message("conv_3", "user", "hello 3")
        # Access conv_1 to make it recently used
        mem.get_history("conv_1")
        # Add conv_4, should evict conv_2 (oldest untouched)
        mem.add_message("conv_4", "user", "hello 4")
        assert "conv_2" not in mem.conversations
        assert "conv_1" in mem.conversations

    def test_get_stats(self):
        """get_stats 返回正确的统计信息"""
        import os
        os.environ["DATABASE_URL"] = "sqlite:///./test_lru_stats.db"
        from app.memory.local_memory import LocalMemory
        mem = LocalMemory(max_history=10, max_conversations=100)
        # Use unique conversation IDs to avoid cross-test pollution
        import uuid
        c1 = f"stats_{uuid.uuid4().hex[:8]}"
        c2 = f"stats_{uuid.uuid4().hex[:8]}"
        mem.add_message(c1, "user", "hello")
        mem.add_message(c1, "assistant", "hi")
        mem.add_message(c2, "user", "test")
        stats = mem.get_stats()
        assert stats["active_conversations"] >= 2
        assert stats["total_messages"] >= 3
        assert stats["max_conversations"] == 100
        # Cleanup
        if os.path.exists("test_lru_stats.db"):
            os.remove("test_lru_stats.db")

    def test_no_eviction_below_max(self):
        """未达到 max_conversations 时不淘汰"""
        from app.memory.local_memory import LocalMemory
        mem = LocalMemory(max_history=10, max_conversations=5)
        for i in range(5):
            mem.add_message(f"conv_{i}", "user", f"hello {i}")
        assert len(mem.conversations) == 5


class TestMemoryPersistence:
    def test_persistence_across_instances(self):
        from app.memory.local_memory import LocalMemory
        conv_id = "persist_test"
        mem1 = LocalMemory(max_history=10)
        mem1.add_message(conv_id, "user", "持久化测试消息")
        mem2 = LocalMemory(max_history=10)
        history = mem2.get_history(conv_id)
        if mem2._db_available:
            assert len(history) >= 1
            assert any("持久化测试消息" in m["content"] for m in history)
        mem2.clear_history(conv_id)

    def teardown_class(self):
        if os.path.exists("./test_memory.db"):
            os.remove("./test_memory.db")