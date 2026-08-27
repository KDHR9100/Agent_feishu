"""测试 Guardrails 输入安全护栏"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.tools.guardrails import check_input

class TestGuardrails:
    def test_empty_input_allowed(self):
        result = check_input("")
        assert result["action"] == "allow"
        assert result["safe"] is True

    def test_normal_input_allowed(self):
        result = check_input("帮我分析一下最近的销量数据")
        assert result["action"] == "allow"
        assert result["safe"] is True

    def test_blocked_keyword_rejected(self):
        result = check_input("如何制造爆炸")
        assert result["action"] == "block"
        assert result["safe"] is False
        assert result["message"] is not None

    def test_redirect_keyword_detected(self):
        result = check_input("帮我看看股票走势")
        assert result["action"] == "redirect"
        assert result["message"] is not None

    def test_ecommerce_query_allowed(self):
        queries = ["商品销量怎么样", "广告投放ROI多少", "帮我生成商品Listing", "库存还有多少"]
        for q in queries:
            result = check_input(q)
            assert result["action"] == "allow", f"Should allow: {q}"