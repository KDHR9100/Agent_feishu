"""Tests for keyword_tool and ticket_tool"""
import os
import pytest


class TestKeywordTool:
    def test_analyze_known_keyword(self):
        from app.tools.keyword_tool import keyword_tool
        result = keyword_tool.analyze_keyword("连衣裙")
        assert result["keyword"] == "连衣裙"
        assert result["search_volume"] == 85000
        assert result["difficulty"] == "high"
        assert len(result["long_tail_keywords"]) > 0

    def test_analyze_unknown_keyword(self):
        from app.tools.keyword_tool import keyword_tool
        result = keyword_tool.analyze_keyword("xyz123abc")
        assert result["keyword"] == "xyz123abc"
        assert result["search_volume"] == "N/A"
        assert result["difficulty"] == "unknown"

    def test_get_hot_keywords_taobao(self):
        from app.tools.keyword_tool import keyword_tool
        result = keyword_tool.get_hot_keywords("taobao")
        assert result["platform"] == "taobao"
        assert len(result["hot_keywords"]) > 0
        assert "连衣裙" in result["hot_keywords"]

    def test_get_hot_keywords_fallback(self):
        from app.tools.keyword_tool import keyword_tool
        result = keyword_tool.get_hot_keywords("unknown_platform")
        assert result["platform"] == "unknown_platform"
        # Falls back to taobao keywords
        assert len(result["hot_keywords"]) > 0


class TestTicketTool:
    def setup_method(self):
        # Use temp DB for testing
        self.db_path = "test_tickets.db"
        os.environ["TICKET_DB"] = self.db_path

    def teardown_method(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_create_ticket(self):
        from app.tools.ticket_tool import TicketTool
        tool = TicketTool(db_path=self.db_path)
        result = tool.create_ticket(
            order_id="ORD001",
            category="退货",
            description="商品有瑕疵",
            phone="13800138000",
        )
        assert result["success"] is True
        assert result["ticket_id"] == 1

    def test_query_order(self):
        from app.tools.ticket_tool import TicketTool
        tool = TicketTool(db_path=self.db_path)
        tool.create_ticket(order_id="ORD002", description="测试工单")
        result = tool.query_order("ORD002")
        assert result["count"] == 1
        assert result["tickets"][0]["order_id"] == "ORD002"

    def test_query_order_not_found(self):
        from app.tools.ticket_tool import TicketTool
        tool = TicketTool(db_path=self.db_path)
        result = tool.query_order("NONEXIST")
        assert result["count"] == 0

    def test_query_by_phone(self):
        from app.tools.ticket_tool import TicketTool
        tool = TicketTool(db_path=self.db_path)
        tool.create_ticket(phone="13900139000", description="咨询")
        result = tool.query_by_phone("13900139000")
        assert result["count"] == 1

    def test_update_status(self):
        from app.tools.ticket_tool import TicketTool
        tool = TicketTool(db_path=self.db_path)
        tool.create_ticket(description="测试")
        result = tool.update_status(1, "resolved")
        assert result["success"] is True
        assert result["status"] == "resolved"

    def test_update_status_invalid(self):
        from app.tools.ticket_tool import TicketTool
        tool = TicketTool(db_path=self.db_path)
        result = tool.update_status(999, "invalid_status")
        assert result["success"] is False

    def test_get_ticket(self):
        from app.tools.ticket_tool import TicketTool
        tool = TicketTool(db_path=self.db_path)
        tool.create_ticket(description="查询测试")
        result = tool.get_ticket(1)
        assert result["success"] is True
        assert result["ticket"]["description"] == "查询测试"
