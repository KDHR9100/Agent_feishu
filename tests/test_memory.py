"""测试会话记忆（内存 + SQLite 持久化）"""
import os, sys, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///./test_memory.db"

class TestLocalMemory:
    def setup_method(self):
        from app.memory.local_memory import LocalMemory
        self.memory = LocalMemory(max_history=5)

    def test_add_and_get_message(self):
        self.memory.add_message("conv1", "user", "你好")
        self.memory.add_message("conv1", "assistant", "你好，有什么可以帮你？")
        history = self.memory.get_history("conv1")
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
        self.memory.add_message("conv_a", "user", "hello_a")
        self.memory.add_message("conv_b", "user", "hello_b")
        assert len(self.memory.get_history("conv_a")) == 1
        assert len(self.memory.get_history("conv_b")) == 1

    def test_format_history(self):
        self.memory.add_message("conv5", "user", "问题")
        self.memory.add_message("conv5", "assistant", "回答")
        formatted = self.memory.format_history("conv5")
        assert "user: 问题" in formatted
        assert "assistant: 回答" in formatted


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