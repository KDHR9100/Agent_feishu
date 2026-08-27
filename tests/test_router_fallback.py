"""Unit tests for keyword fallback routing"""
import pytest
from unittest.mock import patch, MagicMock
from app.agent.router import keyword_fallback, router, KEYWORD_RULES


class TestKeywordFallback:
    def test_single_keyword_match(self):
        assert keyword_fallback("帮我看看库存情况") == ["inventory_skill"]

    def test_multi_keyword_same_skill(self):
        assert keyword_fallback("库存不够了，需要补货") == ["inventory_skill"]

    def test_multi_skill_highest_wins(self):
        assert keyword_fallback("广告投放的ROI和花费怎么样") == ["ads_skill"]

    def test_no_match_returns_empty(self):
        assert keyword_fallback("今天天气怎么样") == []

    def test_all_skills_have_keywords(self):
        for skill, keywords in KEYWORD_RULES.items():
            assert len(keywords) > 0

    def test_rag_skill_match(self):
        assert keyword_fallback("佣金规则是什么") == ["rag_skill"]

    def test_seo_skill_match(self):
        assert keyword_fallback("帮我做SEO关键词分析") == ["seo_skill"]

    def test_support_skill_match(self):
        assert keyword_fallback("我要退款，订单号123") == ["support_skill"]


class TestRouterFallback:
    def _make_state(self, user_input):
        return {"user_input": user_input, "conversation_id": "test", "history": []}

    @patch("app.agent.router._get_llm_with_tools")
    def test_llm_exception_triggers_fallback(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = RuntimeError("API failed")
        mock_get_llm.return_value = mock_llm
        state = self._make_state("帮我分析一下商品销量")
        result = router(state)
        assert result["intent"] == "product_skill"

    @patch("app.agent.router._get_llm_with_tools")
    def test_llm_timeout_triggers_fallback(self, mock_get_llm):
        from app.utils.timeout import TimeoutException
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = TimeoutException("timed out")
        mock_get_llm.return_value = mock_llm
        state = self._make_state("库存预警有哪些")
        result = router(state)
        assert result["intent"] == "inventory_skill"

    @patch("app.agent.router._get_llm_with_tools")
    def test_llm_no_tool_calls_triggers_fallback(self, mock_get_llm):
        mock_response = MagicMock()
        mock_response.tool_calls = []
        mock_response.response_metadata = None
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = mock_response
        mock_get_llm.return_value = mock_llm
        state = self._make_state("佣金规则是什么")
        result = router(state)
        assert result["intent"] == "rag_skill"

    @patch("app.agent.router._get_llm_with_tools")
    def test_llm_success_unchanged(self, mock_get_llm):
        mock_response = MagicMock()
        mock_response.tool_calls = [{"name": "ads_skill", "args": {"user_input": "ad"}}]
        mock_response.response_metadata = None
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = mock_response
        mock_get_llm.return_value = mock_llm
        state = self._make_state("广告效果怎么样")
        result = router(state)
        assert result["intent"] == "ads_skill"
        assert result["skills_to_execute"] == ["ads_skill"]

    @patch("app.agent.router._get_llm_with_tools")
    def test_llm_fail_no_keyword_goes_unknown(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = RuntimeError("fail")
        mock_get_llm.return_value = mock_llm
        state = self._make_state("你好呀")
        result = router(state)
        assert result["intent"] == "unknown"

    def test_file_shortcut_still_works(self):
        state = {
            "user_input": "[文件] sales.xlsx",
            "conversation_id": "test",
            "history": [],
            "file_path": "/tmp/sales.xlsx",
            "file_content": "col1,col2\n1,2",
        }
        result = router(state)
        assert result["intent"] == "file_analysis_skill"