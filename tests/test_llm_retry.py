"""测试 s11 错误恢复 + s08 上下文压缩"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import MagicMock, patch

from app.utils.llm_retry import (
    classify_error, invoke_with_recovery, _exponential_backoff,
)
from app.memory.local_memory import (
    estimate_tokens, estimate_messages_tokens, compact_messages,
)


class TestClassifyError:
    def test_rate_limit_429(self):
        assert classify_error(Exception("Error 429 Too Many Requests")) == "rate_limit"
    def test_rate_limit_529(self):
        assert classify_error(Exception("529 Overloaded")) == "rate_limit"
    def test_context_overflow(self):
        assert classify_error(Exception("context_length_exceeded")) == "context_overflow"
    def test_timeout(self):
        assert classify_error(Exception("Request timed out")) == "timeout"
    def test_other(self):
        assert classify_error(Exception("Connection refused")) == "other"


class TestExponentialBackoff:
    def test_backoff_increases(self):
        delays = [_exponential_backoff(i) for i in range(5)]
        assert delays[0] < delays[2] < delays[4]
    def test_backoff_capped(self):
        assert _exponential_backoff(20) <= 16.0 + 16.0 * 0.3 + 0.01


class TestInvokeWithRecovery:
    def test_success_no_retry(self):
        llm = MagicMock()
        llm.invoke.return_value = "ok"
        assert invoke_with_recovery(llm, []) == "ok"
        assert llm.invoke.call_count == 1

    def test_rate_limit_retry(self):
        llm = MagicMock()
        llm.invoke.side_effect = [Exception("429 rate limit"), "ok"]
        with patch("app.utils.llm_retry.time.sleep"):
            assert invoke_with_recovery(llm, []) == "ok"
        assert llm.invoke.call_count == 2

    def test_context_overflow_compact(self):
        llm = MagicMock()
        llm.invoke.side_effect = [Exception("context_length_exceeded"), "ok"]
        cb = MagicMock(return_value=[])
        assert invoke_with_recovery(llm, [], on_context_overflow=cb) == "ok"
        assert cb.call_count == 1

    def test_compact_only_once(self):
        llm = MagicMock()
        llm.invoke.side_effect = [Exception("context_length_exceeded"), Exception("context_length_exceeded")]
        cb = MagicMock(return_value=[])
        with pytest.raises(Exception):
            invoke_with_recovery(llm, [], on_context_overflow=cb)
        assert cb.call_count == 1

    def test_fallback_switch(self):
        main = MagicMock()
        main.invoke.side_effect = Exception("internal error")
        fb = MagicMock()
        fb.invoke.return_value = "fb_ok"
        assert invoke_with_recovery(main, [], fallback_llm=fb) == "fb_ok"

    def test_all_exhausted(self):
        main = MagicMock()
        main.invoke.side_effect = Exception("conn refused")
        fb = MagicMock()
        fb.invoke.side_effect = Exception("conn refused")
        with pytest.raises(Exception):
            invoke_with_recovery(main, [], fallback_llm=fb)


class TestEstimateTokens:
    def test_empty(self):
        assert estimate_tokens("") == 0
    def test_nonzero(self):
        assert estimate_tokens("中文测试") > 0
    def test_longer_more(self):
        assert estimate_tokens("长文本" * 100) > estimate_tokens("短")


class TestCompactMessages:
    def test_short_unchanged(self):
        from langchain_core.messages import HumanMessage, SystemMessage
        msgs = [SystemMessage(content="sys"), HumanMessage(content="hi")]
        assert compact_messages(msgs, max_tokens=99999) is msgs
    def test_long_trimmed(self):
        from langchain_core.messages import HumanMessage, SystemMessage
        msgs = [SystemMessage(content="s")] + [HumanMessage(content="x" * 200) for _ in range(50)]
        result = compact_messages(msgs, max_tokens=500)
        assert len(result) < len(msgs)
        assert any("已省略" in str(m.content) for m in result)
    def test_empty(self):
        assert compact_messages([]) == []
    def test_preserves_head_tail(self):
        from langchain_core.messages import HumanMessage, SystemMessage
        msgs = [SystemMessage(content="head")] + [HumanMessage(content="m%d" % i) for i in range(40)]
        result = compact_messages(msgs, max_tokens=200)
        assert result[0].content == "head"
        assert "m39" in str(result[-1].content)


class TestCompressionOrder:
    def test_trim_before_summarize(self):
        from app.memory.local_memory import LocalMemory
        mem = LocalMemory(max_history=10, max_conversations=100)
        mem._db_available = False
        with patch.object(mem, "_summarize_old_messages") as mock_s:
            for i in range(12):
                mem.add_message("c1", "user", "msg %d" % i)
            assert mock_s.call_count == 0
            assert len(mem.conversations["c1"]) <= 10
