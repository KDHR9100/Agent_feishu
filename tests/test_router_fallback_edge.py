"""Edge case tests for keyword fallback routing"""
import pytest
from unittest.mock import patch, MagicMock
from app.agent.router import keyword_fallback, router, KEYWORD_RULES


class TestKeywordFallbackEdgeCases:
    """keyword_fallback boundary tests"""

    def test_empty_string(self):
        assert keyword_fallback("") == []

    def test_whitespace_only(self):
        assert keyword_fallback("   \n\t  ") == []

    def test_pure_punctuation(self):
        assert keyword_fallback("!!!???...") == []

    def test_english_only_no_match(self):
        assert keyword_fallback("hello world how are you") == []

    def test_mixed_case_seo(self):
        # KEYWORD_RULES has both "SEO" and "seo"
        assert keyword_fallback("Seo优化") == ["seo_skill"]

    def test_keyword_in_long_text(self):
        long_text = "我" * 500 + "库存" + "告" * 500
        assert keyword_fallback(long_text) == ["inventory_skill"]

    def test_ambiguous_multi_category(self):
        # "商品" -> product, "广告" -> ads, both 1 hit
        # max() picks first encountered in dict order
        result = keyword_fallback("商品广告")
        assert len(result) == 1
        assert result[0] in ("product_skill", "ads_skill")

    def test_tie_breaking_deterministic(self):
        # Same input should always give same result
        r1 = keyword_fallback("商品广告")
        r2 = keyword_fallback("商品广告")
        assert r1 == r2

    def test_all_keywords_individually(self):
        # Every single keyword should map to its skill
        for skill, keywords in KEYWORD_RULES.items():
            for kw in keywords:
                result = keyword_fallback(kw)
                assert result == [skill], f"keyword '{kw}' expected {skill}, got {result}"

    def test_substring_false_positive(self):
        # "库" alone should NOT match "库存"
        assert keyword_fallback("仓库管理") == []

    def test_partial_keyword_no_match(self):
        # "ROI" is a keyword, but "BROI" contains it as substring
        # Current impl uses `in` so "BROI" WILL match - document this behavior
        result = keyword_fallback("BROI测试")
        assert result == ["ads_skill"]  # substring match is by design

    def test_newline_in_input(self):
        assert keyword_fallback("第一行\n库存不足\n第三行") == ["inventory_skill"]

    def test_special_characters_around_keyword(self):
        assert keyword_fallback("【库存】预警！！！") == ["inventory_skill"]

    def test_very_long_input_performance(self):
        import time
        huge_input = "电商运营" * 10000  # ~40k chars
        start = time.time()
        keyword_fallback(huge_input)
        elapsed = time.time() - start
        assert elapsed < 0.1, f"keyword_fallback too slow: {elapsed:.3f}s"


class TestRouterEdgeCases:
    """Router-level edge cases with mocked LLM"""

    def _make_state(self, user_input, **kwargs):
        state = {"user_input": user_input, "conversation_id": "test", "history": []}
        state.update(kwargs)
        return state

    @patch("app.agent.router._get_llm_with_tools")
    def test_llm_returns_none_response(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = None
        mock_get_llm.return_value = mock_llm
        state = self._make_state("库存不够了")
        result = router(state)
        assert result["intent"] == "inventory_skill"

    @patch("app.agent.router._get_llm_with_tools")
    def test_concurrent_timeout_exception(self, mock_get_llm):
        from concurrent.futures import TimeoutError as FuturesTimeout
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = FuturesTimeout()
        mock_get_llm.return_value = mock_llm
        state = self._make_state("退款怎么处理")
        result = router(state)
        assert result["intent"] == "support_skill"

    @patch("app.agent.router._get_llm_with_tools")
    def test_empty_user_input_llm_fails(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = RuntimeError("fail")
        mock_get_llm.return_value = mock_llm
        state = self._make_state("")
        result = router(state)
        assert result["intent"] == "unknown"
    @patch("app.agent.router._get_llm_with_tools")
    def test_history_does_not_affect_fallback(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = RuntimeError("fail")
        mock_get_llm.return_value = mock_llm
        state = self._make_state(
            "SEO标题优化",
            history=[
                {"role": "user", "content": "prev q"},
                {"role": "assistant", "content": "prev a"},
            ]
        )
        result = router(state)
        assert result["intent"] == "seo_skill"

    @patch("app.agent.router._get_llm_with_tools")
    def test_reflect_feedback_cleared_on_fallback(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = RuntimeError("fail")
        mock_get_llm.return_value = mock_llm
        state = self._make_state("商品分析", reflect_feedback="try ads")
        result = router(state)
        assert result.get("reflect_feedback") is None

    @patch("app.agent.router._get_llm_with_tools")
    def test_file_shortcut_priority_over_fallback(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_get_llm.return_value = mock_llm
        state = self._make_state(
            "分析这个文件",
            file_path="/tmp/data.xlsx",
            file_content="a,b\n1,2",
        )
        result = router(state)
        assert result["intent"] == "file_analysis_skill"
        mock_llm.invoke.assert_not_called()

    @patch("app.agent.router._get_llm_with_tools")
    def test_llm_multiple_tool_calls_preserved(self, mock_get_llm):
        mock_response = MagicMock()
        mock_response.tool_calls = [
            {"name": "product_skill", "args": {"user_input": "x"}},
            {"name": "ads_skill", "args": {"user_input": "x"}},
        ]
        mock_response.response_metadata = None
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = mock_response
        mock_get_llm.return_value = mock_llm
        state = self._make_state("商品和广告一起分析")
        result = router(state)
        assert result["skills_to_execute"] == ["product_skill", "ads_skill"]