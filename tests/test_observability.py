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


class TestTokenCoverage:

    def _fake_llm_result(self, prompt=100, completion=20):
        """构造带 token_usage 的 LLMResult 替身"""
        result = MagicMock()
        result.llm_output = {"token_usage": {
            "prompt_tokens": prompt, "completion_tokens": completion}}
        return result

    def test_unattributed_calls_are_not_dropped(self, monkeypatch):
        """未标记 track_as 的 LLM 调用归入 unattributed, 不再静默丢弃"""
        recorded = []

        def _spy(skill_name, input_tokens, output_tokens, conversation_id=""):
            recorded.append((skill_name, input_tokens, output_tokens))

        import app.monitoring as mon_pkg
        monkeypatch.setattr(mon_pkg.monitoring_stats, "record_token_usage", _spy)

        from app.utils import token_tracker as tt
        handler = tt.TokenTrackingHandler()
        # 清空线程上下文: 模拟未设 track_as 的调用路径
        monkeypatch.setattr(tt, "get_context", lambda: (None, None))
        handler.on_llm_end(self._fake_llm_result(prompt=500, completion=80))

        assert recorded == [("unattributed", 500, 80)]

    def test_attributed_calls_keep_owner(self, monkeypatch):
        """已标记归属的调用不受兜底逻辑影响"""
        recorded = []

        def _spy(skill_name, input_tokens, output_tokens, conversation_id=""):
            recorded.append((skill_name, input_tokens, output_tokens))

        import app.monitoring as mon_pkg
        monkeypatch.setattr(mon_pkg.monitoring_stats, "record_token_usage", _spy)

        from app.utils import token_tracker as tt
        handler = tt.TokenTrackingHandler()
        monkeypatch.setattr(tt, "get_context",
                            lambda: ("router", "conv-1"))
        handler.on_llm_end(self._fake_llm_result(prompt=300, completion=10))

        assert recorded == [("router", 300, 10)]

    def test_zero_usage_still_skipped(self, monkeypatch):
        """无 token 数据(如流式无 usage)仍不记账, 避免噪声行"""
        recorded = []

        def _spy(*args, **kwargs):
            recorded.append(args)

        import app.monitoring as mon_pkg
        monkeypatch.setattr(mon_pkg.monitoring_stats, "record_token_usage", _spy)

        from app.utils import token_tracker as tt
        handler = tt.TokenTrackingHandler()
        monkeypatch.setattr(tt, "get_context", lambda: (None, None))
        handler.on_llm_end(self._fake_llm_result(prompt=0, completion=0))

        assert recorded == []


class TestGuardrailsUsageRecording:

    def test_review_usage_recorded(self, monkeypatch):
        """guardrails 裸 requests 调用的 token 手工记账"""
        recorded = []

        def _spy(skill_name, input_tokens, output_tokens, conversation_id=""):
            recorded.append((skill_name, input_tokens, output_tokens))

        import app.monitoring as mon_pkg
        monkeypatch.setattr(mon_pkg.monitoring_stats, "record_token_usage", _spy)

        from app.tools.guardrails import _record_review_usage
        _record_review_usage({"usage": {"prompt_tokens": 420, "completion_tokens": 3}})
        assert recorded == [("guardrails", 420, 3)]

    def test_review_usage_missing_is_noop(self, monkeypatch):
        recorded = []

        def _spy(*args, **kwargs):
            recorded.append(args)

        import app.monitoring as mon_pkg
        monkeypatch.setattr(mon_pkg.monitoring_stats, "record_token_usage", _spy)

        from app.tools.guardrails import _record_review_usage
        _record_review_usage({})
        _record_review_usage(None)
        _record_review_usage({"usage": {"prompt_tokens": 0, "completion_tokens": 0}})
        assert recorded == []