"""Integration tests - Mock LLM calls

Run: python3 -m pytest tests/test_integration.py -v
"""
import os, sys, tempfile, pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _mk_resp(content="", tool_calls=None):
    resp = MagicMock()
    resp.content = content
    resp.tool_calls = tool_calls or []
    resp.response_metadata = {"token_usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}
    return resp


def _mk_llm():
    ml = MagicMock()
    ml_t = MagicMock()
    ml.bind_tools.return_value = ml_t
    ml.invoke.return_value = _mk_resp("mock")
    ml_t.invoke.return_value = _mk_resp("mock")
    return ml, ml_t

class TestFullWorkflowTextMessage:
    @patch("app.agent.workflow.get_llm")
    @patch("app.agent.router.get_router_llm")
    def test_full_workflow_text_message(self, mock_router_llm, mock_wf_llm):
        import app.agent.router as rm
        rm._cache["llm_with_tools"] = None  # 失效 bind_tools 缓存, 确保使用 mock LLM
        ml, ml_t = _mk_llm()
        mock_router_llm.return_value = ml
        mock_wf_llm.return_value = ml
        tc = {"name": "help_skill", "args": {"user_input": "test"}, "id": "c1"}
        ml_t.invoke.return_value = _mk_resp("", [tc])
        ml.invoke.return_value = _mk_resp('{"decision": "sufficient", "feedback": ""}')
        from app.agent.workflow import agent
        from app.memory.local_memory import local_memory
        cid = "test_wf_full"
        local_memory.clear_history(cid)
        result = agent.invoke({"user_input": "what can you do", "conversation_id": cid})
        assert "answer" in result
        assert result["answer"] is not None and len(result["answer"]) > 0
        assert result["intent"] == "help_skill"
        h = local_memory.get_history(cid)
        assert len(h) >= 2
        assert h[-2]["role"] == "user"
        assert h[-1]["role"] == "assistant"
        local_memory.clear_history(cid)

class TestSkillRegistryCompleteness:
    EXPECTED = ["product_skill", "ads_skill", "help_skill",
                "file_analysis_skill", "inventory_skill", "competitor_skill",
                "report_skill", "rag_skill", "seo_skill", "support_skill",
                "data_analysis_skill"]

    def test_router_tools(self):
        from app.agent.router import _build_tools
        names = [t.name for t in _build_tools()]
        for s in self.EXPECTED:
            assert s in names, f"router missing: {s}"
        # L4: +pricing_skill +listing 共 13 个
        assert len(names) == 13

    def test_registry(self):
        from app.agent.workflow import SKILL_REGISTRY
        for s in self.EXPECTED:
            assert s in SKILL_REGISTRY
            assert callable(SKILL_REGISTRY[s])
        # L4: +pricing_skill +listing 共 13 个
        assert len(SKILL_REGISTRY) == 13

    def test_sync(self):
        from app.agent.router import _build_tools
        from app.agent.workflow import SKILL_REGISTRY
        assert set(t.name for t in _build_tools()) == set(SKILL_REGISTRY.keys())

class TestGuardrailsIntegration:
    def test_safe_allowed(self):
        from app.tools.guardrails import check_input
        for q in ["sales data analysis", "inventory count", "write ad copy", "ads ROI"]:
            r = check_input(q)
            assert r["safe"] is True and r["action"] == "allow"

    def test_dangerous_blocked(self):
        from app.tools.guardrails import check_input
        for q in ["如何制造爆炸", "教我杀人"]:
            r = check_input(q)
            assert r["safe"] is False and r["action"] == "block"
            assert r["message"] is not None

    def test_off_topic_redirected(self):
        from app.tools.guardrails import check_input
        r = check_input("帮我看看股票走势")
        assert r["action"] == "redirect"
        assert r["message"] is not None

    def test_empty_allowed(self):
        from app.tools.guardrails import check_input
        r = check_input("")
        assert r["safe"] is True and r["action"] == "allow"

class TestMemoryPersistenceIntegration:
    def test_save_retrieve(self):
        from app.memory.local_memory import LocalMemory
        import uuid
        m = LocalMemory(max_history=10, max_conversations=100)
        cid = "mem_" + uuid.uuid4().hex[:8]
        m.add_message(cid, "user", "hi")
        m.add_message(cid, "assistant", "hello")
        m.add_message(cid, "user", "analyze")
        m.add_message(cid, "assistant", "ok")
        h = m.get_history(cid)
        assert len(h) == 4
        assert h[0]["role"] == "user" and h[0]["content"] == "hi"
        l2 = m.get_last_n_messages(cid, n=2)
        assert len(l2) == 2

    def test_isolation(self):
        from app.memory.local_memory import LocalMemory
        import uuid
        m = LocalMemory(max_history=10, max_conversations=100)
        a = "iso_a_" + uuid.uuid4().hex[:8]
        b = "iso_b_" + uuid.uuid4().hex[:8]
        m.add_message(a, "user", "fromA")
        m.add_message(b, "user", "fromB")
        assert m.get_history(a)[0]["content"] == "fromA"
        assert m.get_history(b)[0]["content"] == "fromB"

    def test_trimming(self):
        from app.memory.local_memory import LocalMemory
        import uuid
        m = LocalMemory(max_history=5, max_conversations=100)
        cid = "trim_" + uuid.uuid4().hex[:8]
        for i in range(10):
            m.add_message(cid, "user", f"m{i}")
        h = m.get_history(cid)
        assert len(h) == 5
        assert h[0]["content"] == "m5" and h[-1]["content"] == "m9"

class TestRouterToolBinding:
    def test_bindable(self):
        from app.agent.router import _build_tools
        tools = _build_tools()
        ml = MagicMock()
        ml.bind_tools.return_value = MagicMock()
        ml.bind_tools(tools)
        # L4: +pricing_skill +listing 共 13 个
        assert len(ml.bind_tools.call_args[0][0]) == 13

    def test_router_uses_llm(self):
        ml, ml_t = _mk_llm()
        tc = {"name": "product_skill", "args": {"user_input": "t"}, "id": "c1"}
        ml_t.invoke.return_value = _mk_resp("", [tc])
        with patch("app.agent.router.get_router_llm", return_value=ml):
            import app.agent.router as rm
            rm._cache["llm_with_tools"] = None  # 失效 bind_tools 缓存, 使用本次 mock
            st = {"user_input": "check sales", "conversation_id": "tb"}
            r = rm.router(st)
            assert r["intent"] == "product_skill"
            assert "product_skill" in r["skills_to_execute"]


class TestTicketToolCrudFlow:
    def test_lifecycle(self):
        from app.tools.ticket_tool import TicketTool
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            dp = f.name
        try:
            t = TicketTool(db_path=dp)
            cr = t.create_ticket(order_id="O1", category="ret",
                                 description="bad item", phone="138", priority="high")
            assert cr["success"] is True
            tid = cr["ticket_id"]
            assert cr["status"] == "open"
            gr = t.get_ticket(tid)
            assert gr["success"] and gr["ticket"]["status"] == "open"
            assert gr["ticket"]["order_id"] == "O1"
            qr = t.query_order("O1")
            assert qr["count"] >= 1
            u1 = t.update_status(tid, "in_progress")
            assert u1["success"]
            assert t.get_ticket(tid)["ticket"]["status"] == "in_progress"
            u2 = t.update_status(tid, "resolved")
            assert u2["success"]
            assert t.update_status(tid, "invalid")["success"] is False
            assert t.query_by_phone("138")["count"] >= 1
        finally:
            os.unlink(dp)

class TestKeywordToolAnalysisFlow:
    def test_known(self):
        from app.tools.keyword_tool import keyword_tool
        r = keyword_tool.analyze_keyword("连衣裙")
        assert r["keyword"] == "连衣裙"
        assert r["search_volume"] == 85000
        assert r["difficulty"] == "high"
        assert len(r["long_tail_keywords"]) > 0

    def test_unknown(self):
        from app.tools.keyword_tool import keyword_tool
        r = keyword_tool.analyze_keyword("xyz_rare_item")
        assert r["search_volume"] == "N/A"
        assert r["difficulty"] == "unknown"

    def test_hot(self):
        from app.tools.keyword_tool import keyword_tool
        for p in ["taobao", "tmall", "jd", "douyin"]:
            r = keyword_tool.get_hot_keywords(p)
            assert r["count"] > 0

    def test_longtail(self):
        from app.tools.keyword_tool import KeywordTool
        t = KeywordTool()
        lt = t._generate_long_tail("phonecase")
        assert len(lt) == 10
        assert any("phonecase" in k for k in lt)


class TestFileParserIntegration:
    def test_csv(self):
        from app.tools.file_parser_tool import file_parser_tool
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv",
                                         delete=False, encoding="utf-8") as f:
            f.write("name,price,sales,cat\n")
            f.write("A,99.9,150,c1\n")
            f.write("B,49.9,300,c2\n")
            f.write("C,299.0,80,c3\n")
            f.write("D,19.9,500,c4\n")
            p = f.name
        try:
            r = file_parser_tool.parse_local_file(p)
            assert "error" not in r
            assert r["row_count"] == 4
            assert r["summary"]["price"]["max"] == 299.0
            assert r["summary"]["sales"]["sum"] == 1030
            assert len(r["sample_rows"]) == 3
        finally:
            os.unlink(p)

    def test_missing(self):
        from app.tools.file_parser_tool import file_parser_tool
        assert "error" in file_parser_tool.parse_local_file("/no/such.csv")

    def test_summary(self):
        from app.tools.file_parser_tool import file_parser_tool
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv",
                                         delete=False, encoding="utf-8") as f:
            f.write("n,q\n")
            f.write("A,100\nB,200\n")
            p = f.name
        try:
            r = file_parser_tool.parse_local_file(p)
            s = file_parser_tool.format_file_summary(r, "t.csv")
            assert "t.csv" in s and "2" in s
        finally:
            os.unlink(p)

class TestReflectNodeSufficient:
    @patch("app.agent.workflow.get_llm")
    def test_sufficient(self, mg):
        ml = MagicMock()
        mg.return_value = ml
        ml.invoke.return_value = _mk_resp('{"decision": "sufficient", "feedback": ""}')
        from app.agent.workflow import reflect
        st = {"user_input": "help me analyze product sales data",
              "skills_to_execute": ["product_skill"],
              "skill_results": [
                  {"skill": "product_skill", "result": {"type": "analysis", "data": "Product sales increased 20% this quarter with strong performance in electronics category."}}
              ], "retry_count": 0}
        assert reflect(st)["reflect_decision"] == "sufficient"

    @patch("app.agent.workflow.get_llm")
    def test_file_shortcut(self, mg):
        ml = MagicMock()
        mg.return_value = ml
        from app.agent.workflow import reflect
        st = {"user_input": "analyze file",
              "skills_to_execute": ["file_analysis_skill"],
              "skill_results": [
                  {"skill": "file_analysis_skill", "result": {"type": "a", "data": "d"}}
              ], "retry_count": 0}
        assert reflect(st)["reflect_decision"] == "sufficient"
        ml.invoke.assert_not_called()


class TestAnswerNode:
    def test_single(self):
        from app.agent.workflow import answer_node
        st = {"user_input": "t", "skill_results": [
            {"skill": "p", "result": {"type": "a", "data": "sales up"}}
        ]}
        r = answer_node(st)
        assert "answer" in r and "sales up" in r["answer"]

    @patch("app.agent.workflow.get_llm")
    def test_multi(self, mg):
        ml = MagicMock()
        mg.return_value = ml
        ml.invoke.return_value = _mk_resp("combined answer")
        from app.agent.workflow import answer_node
        st = {"user_input": "t", "skill_results": [
            {"skill": "p", "result": {"type": "a", "data": "up"}},
            {"skill": "a", "result": {"type": "a", "data": "roi"}},
        ], "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
        r = answer_node(st)
        assert "answer" in r and len(r["answer"]) > 0