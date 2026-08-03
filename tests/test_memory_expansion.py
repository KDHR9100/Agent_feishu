"""任务1: 记忆系统扩容 - 30条加载 + 自动摘要压缩 单元测试"""
import os
import sys
import uuid
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.memory.local_memory import LocalMemory, SUMMARIZE_THRESHOLD, RECENT_KEEP_COUNT


class TestMemoryExpansion:

    def setup_method(self):
        self.memory = LocalMemory(max_history=60, max_conversations=100)
        self.cid = str(uuid.uuid4())

    def test_default_max_history_is_60(self):
        mem = LocalMemory()
        assert mem.max_history == 60

    def test_load_30_messages(self):
        for i in range(40):
            role = "user" if i % 2 == 0 else "assistant"
            self.memory.add_message(self.cid, role, f"msg_{i}")
        summary, recent = self.memory.get_context(self.cid)
        assert len(recent) == 30
        assert recent[-1]["content"] == "msg_39"
        assert recent[0]["content"] == "msg_10"

    def test_get_context_no_summary_below_threshold(self):
        for i in range(20):
            self.memory.add_message(self.cid, "user", f"msg_{i}")
        summary, recent = self.memory.get_context(self.cid)
        assert summary is None
        assert len(recent) == 20

    def test_constants_defined(self):
        assert SUMMARIZE_THRESHOLD == 50
        assert RECENT_KEEP_COUNT == 30


class TestSummarization:

    def setup_method(self):
        self.memory = LocalMemory(max_history=60, max_conversations=100)
        self.cid = str(uuid.uuid4())

    @patch("app.config.get_llm")
    def test_summarize_triggered_above_threshold(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "用户询问了商品销售和库存情况"
        mock_llm.invoke.return_value = mock_response
        mock_get_llm.return_value = mock_llm

        for i in range(SUMMARIZE_THRESHOLD + 2):
            role = "user" if i % 2 == 0 else "assistant"
            self.memory.add_message(self.cid, role, f"message_{i}")

        assert mock_llm.invoke.called
        summary, recent = self.memory.get_context(self.cid)
        assert summary is not None

    @patch("app.config.get_llm")
    def test_no_summarize_below_threshold(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_get_llm.return_value = mock_llm

        for i in range(SUMMARIZE_THRESHOLD - 1):
            self.memory.add_message(self.cid, "user", f"msg_{i}")

        mock_llm.invoke.assert_not_called()

    @patch("app.config.get_llm")
    def test_summarize_failure_graceful(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = RuntimeError("API timeout")
        mock_get_llm.return_value = mock_llm

        for i in range(SUMMARIZE_THRESHOLD + 2):
            self.memory.add_message(self.cid, "user", f"msg_{i}")

        summary, recent = self.memory.get_context(self.cid)
        assert summary is None
        assert len(recent) == RECENT_KEEP_COUNT

    @patch("app.config.get_llm")
    def test_summary_merged_on_multiple_triggers(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "摘要内容"
        mock_llm.invoke.return_value = mock_response
        mock_get_llm.return_value = mock_llm

        for i in range(SUMMARIZE_THRESHOLD + 2):
            self.memory.add_message(self.cid, "user", f"msg_{i}")

        self.memory._summaries[self.cid] = "旧摘要"
        self.memory._summarize_old_messages(self.cid)

        summary = self.memory._summaries[self.cid]
        assert "旧摘要" in summary


class TestClearHistoryWithSummary:

    def setup_method(self):
        self.memory = LocalMemory(max_history=60, max_conversations=100)
        self.cid = str(uuid.uuid4())

    def test_clear_removes_summary(self):
        self.memory._summaries[self.cid] = "test summary"
        self.memory.add_message(self.cid, "user", "hello")
        self.memory.clear_history(self.cid)
        assert self.cid not in self.memory._summaries
        assert self.memory.get_context(self.cid) == (None, [])


class TestWorkflowIntegration:

    @patch("app.agent.workflow.local_memory")
    def test_load_history_uses_get_context(self, mock_memory):
        from app.agent.workflow import load_history

        mock_memory.get_context.return_value = ("摘要", [{"role": "user", "content": "hi"}])
        state = {"conversation_id": "test-123"}
        result = load_history(state)

        mock_memory.get_context.assert_called_once_with("test-123", n=30)
        assert result["history"] == [{"role": "user", "content": "hi"}]
        assert result["history_summary"] == "摘要"

    @patch("app.agent.workflow.local_memory")
    def test_load_history_no_summary(self, mock_memory):
        from app.agent.workflow import load_history

        mock_memory.get_context.return_value = (None, [{"role": "user", "content": "hi"}])
        state = {"conversation_id": "test-456"}
        result = load_history(state)

        assert result["history_summary"] is None