"""Integration test: real LLM (LM Studio) + keyword fallback
Run: python -m pytest tests/test_router_integration.py -v -s
Requires: LM Studio running on localhost:1234
"""
import time
import pytest
import requests

LM_STUDIO_URL = "http://10.132.226.232:1234/v1"

def lm_studio_available():
    try:
        r = requests.get(f"{LM_STUDIO_URL}/models", timeout=3)
        return r.status_code == 200
    except Exception:
        return False

pytestmark = pytest.mark.skipif(
    not lm_studio_available(),
    reason="LM Studio not running on localhost:1234"
)

ROUTING_CASES = [
    ("帮我分析一下商品销量趋势", "product_skill"),
    ("广告投放的ROI怎么样", "ads_skill"),
    ("库存预警有哪些商品", "inventory_skill"),
    ("竞品分析怎么做", "competitor_skill"),
    ("生成本周运营报告", "report_skill"),
    ("佣金规则是什么", "rag_skill"),
    ("SEO关键词优化建议", "seo_skill"),
    ("我要退款订单号12345", "support_skill"),
    ("销售数据同比环比分析", "data_analysis_skill"),
]


class TestRealLLMRouting:
    @pytest.fixture(autouse=True)
    def setup_router(self):
        import app.agent.router as router_mod
        from unittest.mock import patch
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(
            base_url=LM_STUDIO_URL,
            api_key="lm-studio",
            model="deepseek-r1-distill-nsfw-rp-vredux-proper.i1",
            temperature=0,
            timeout=30,
        )
        self.llm = llm
        router_mod._llm_with_tools = None
        with patch.object(router_mod, "get_llm", return_value=llm):
            yield
        router_mod._llm_with_tools = None

    def test_tool_calling_capability(self):
        from app.agent.router import tools
        from langchain_core.messages import HumanMessage, SystemMessage
        llm_with_tools = self.llm.bind_tools(tools)
        resp = llm_with_tools.invoke([
            SystemMessage(content="Pick the right tool for the user query."),
            HumanMessage(content="帮我分析商品销量"),
        ])
        has_tools = bool(resp.tool_calls)
        print(f"\n[CAPABILITY] tool_calls: {has_tools}")
        if has_tools:
            print(f"[CAPABILITY] selected: {resp.tool_calls[0]['name']}")
        else:
            print(f"[CAPABILITY] raw: {resp.content[:200]}")

    def test_routing_accuracy(self):
        from app.agent.router import router
        results = []
        for user_input, expected in ROUTING_CASES:
            state = {
                "user_input": user_input,
                "conversation_id": "int_test",
                "history": [],
            }
            start = time.time()
            result = router(state)
            elapsed = time.time() - start
            actual = result["intent"]
            results.append((user_input, expected, actual, actual == expected, elapsed))
        print("\n" + "=" * 70)
        print(f"{'Input':<25} {'Expected':<20} {'Actual':<20} {'OK'} {'Time'}")
        print("-" * 70)
        for inp, exp, act, ok, t in results:
            print(f"{inp:<25} {exp:<20} {act:<20} {'Y' if ok else 'N'}  {t:.2f}s")
        print("-" * 70)
        acc = sum(1 for r in results if r[3]) / len(results)
        avg_t = sum(r[4] for r in results) / len(results)
        print(f"Accuracy: {acc:.0%}  Avg latency: {avg_t:.2f}s")
        print("=" * 70)
        assert acc >= 0.5, f"Accuracy too low: {acc:.0%}"

    def test_fallback_latency(self):
        from app.agent.router import keyword_fallback
        start = time.time()
        result = keyword_fallback("库存预警补货建议")
        elapsed = time.time() - start
        assert result == ["inventory_skill"]
        assert elapsed < 0.01
        print(f"\n[FALLBACK] latency: {elapsed*1000:.2f}ms")