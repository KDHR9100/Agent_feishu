"""任务3: API成本与链路可观测性 单元测试"""
import os
import sys
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestTokenUsageLog:

    def test_model_exists(self):
        from app.models.models import TokenUsageLog
        assert hasattr(TokenUsageLog, "__tablename__")
        assert TokenUsageLog.__tablename__ == "token_usage_logs"

    def test_model_columns(self):
        from app.models.models import TokenUsageLog
        cols = {c.name for c in TokenUsageLog.__table__.columns}
        assert "skill_name" in cols
        assert "input_tokens" in cols
        assert "output_tokens" in cols
        assert "total_tokens" in cols
        assert "conversation_id" in cols
        assert "created_at" in cols


class TestRecordTokenUsage:

    @patch("app.models.database.SessionLocal")
    def test_record_writes_to_db(self, mock_session_cls):
        from app.monitoring.stats import MonitoringStats
        stats = MonitoringStats()

        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        stats.record_token_usage(
            skill_name="product_skill",
            input_tokens=100,
            output_tokens=50,
            conversation_id="conv-1",
        )

        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()
        mock_session.close.assert_called_once()

    @patch("app.models.database.SessionLocal")
    def test_record_db_error_graceful(self, mock_session_cls):
        from app.monitoring.stats import MonitoringStats
        stats = MonitoringStats()
        mock_session_cls.side_effect = RuntimeError("DB down")

        # 不应抛异常
        stats.record_token_usage("test_skill", 10, 5)


class TestGetUsageLast24h:

    @patch("app.models.database.SessionLocal")
    def test_returns_ranking(self, mock_session_cls):
        from app.monitoring.stats import MonitoringStats
        stats = MonitoringStats()

        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        mock_row = MagicMock()
        mock_row.skill_name = "ads_skill"
        mock_row.call_count = 5
        mock_row.total_input = 500
        mock_row.total_output = 200
        mock_row.total_tokens = 700

        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.group_by.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = [mock_row]

        result = stats.get_usage_last_24h()
        assert result["period"] == "last_24h"
        assert len(result["skill_ranking"]) == 1
        assert result["skill_ranking"][0]["skill_name"] == "ads_skill"
        assert result["grand_total_tokens"] == 700

    @patch("app.models.database.SessionLocal")
    def test_db_error_returns_error(self, mock_session_cls):
        from app.monitoring.stats import MonitoringStats
        stats = MonitoringStats()
        mock_session_cls.side_effect = RuntimeError("DB down")

        result = stats.get_usage_last_24h()
        assert "error" in result
        assert result["skill_ranking"] == []


class TestTracing:

    def test_trace_node_noop_without_otel(self):
        from app.utils.tracing import trace_node

        @trace_node("test_node")
        def my_func(x):
            return x * 2

        assert my_func(5) == 10

    def test_trace_node_preserves_name(self):
        from app.utils.tracing import trace_node

        @trace_node("test_node")
        def my_special_func():
            pass

        assert my_special_func.__name__ == "my_special_func"

    def test_otel_available_flag(self):
        from app.utils.tracing import OTEL_AVAILABLE
        assert isinstance(OTEL_AVAILABLE, bool)


class TestWorkflowTracing:

    def test_workflow_imports_trace_node(self):
        import inspect
        import app.agent.workflow as wf
        source = inspect.getsource(wf)
        assert "trace_node" in source

    def test_nodes_have_trace_decorator(self):
        import inspect
        import app.agent.workflow as wf
        source = inspect.getsource(wf)
        for node in ["load_history", "save_history", "load_file",
                      "skill_executor", "reflect", "answer"]:
            assert f'@trace_node("{node}")' in source, f"Missing trace on {node}"


class TestMetricsEndpoint:

    def test_main_has_metrics_usage(self):
        import inspect
        import app.main as main_mod
        source = inspect.getsource(main_mod)
        assert "/metrics/usage" in source
        assert "get_usage_last_24h" in source