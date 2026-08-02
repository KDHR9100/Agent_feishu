"""Unit tests for LLM + keyword cross-validation"""
import pytest
from unittest.mock import patch, MagicMock
from app.agent.router import router, _keyword_scores


class TestKeywordScores:
    def test_basic_scoring(self):
        scores = _keyword_scores("佣金规则是什么")
        assert scores.get("rag_skill", 0) >= 2  # "佣金" + "规则"

    def test_single_hit(self):
        scores = _keyword_scores("库存情况")
        assert scores.get("inventory_skill") == 1

    def test_no_hit(self):
        assert _keyword_scores("今天天气") == {}


class TestCrossValidation:
    def _state(self, text):
        return {"user_input": text, "conversation_id": "cv", "history": []}

    @patch("app.agent.router._get_llm_with_tools")
    def test_llm_and_kw_agree(self, mock_get):
        """LLM and keyword agree -> use LLM result"""
        resp = MagicMock()
        resp.tool_calls = [{"name": "inventory_skill", "args": {"user_input": "x"}}]
        resp.response_metadata = None
        m = MagicMock(); m.invoke.return_value = resp
        mock_get.return_value = m
        r = router(self._state("库存预警"))
        assert r["intent"] == "inventory_skill"

    @patch("app.agent.router._get_llm_with_tools")
    def test_llm_wrong_kw_overrides_high_conf(self, mock_get):
        """LLM wrong, keyword conf>=2 -> override to keyword"""
        resp = MagicMock()
        resp.tool_calls = [{"name": "inventory_skill", "args": {"user_input": "x"}}]
        resp.response_metadata = None
        m = MagicMock(); m.invoke.return_value = resp
        mock_get.return_value = m
        # "佣金规则" -> kw gives rag_skill with conf=2
        r = router(self._state("佣金规则是什么"))
        assert r["intent"] == "rag_skill"

    @patch("app.agent.router._get_llm_with_tools")
    def test_llm_wrong_kw_low_conf_keeps_llm(self, mock_get):
        """LLM wrong, keyword conf=1 -> keep LLM"""
        resp = MagicMock()
        resp.tool_calls = [{"name": "product_skill", "args": {"user_input": "x"}}]
        resp.response_metadata = None
        m = MagicMock(); m.invoke.return_value = resp
        mock_get.return_value = m
        # "库存" alone = conf 1 for inventory, LLM chose product -> keep LLM
        r = router(self._state("库存商品分析"))
        assert r["intent"] == "product_skill"

    @patch("app.agent.router._get_llm_with_tools")
    def test_llm_correct_no_kw_match(self, mock_get):
        """LLM correct, no keyword match -> keep LLM"""
        resp = MagicMock()
        resp.tool_calls = [{"name": "help_skill", "args": {"user_input": "x"}}]
        resp.response_metadata = None
        m = MagicMock(); m.invoke.return_value = resp
        mock_get.return_value = m
        r = router(self._state("你好请问你能做什么功能"))
        # "功能" matches help_skill, so they agree
        assert r["intent"] == "help_skill"