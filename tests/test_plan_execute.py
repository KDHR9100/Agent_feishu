"""任务5: Plan-Execute工作流模式 单元测试"""
import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestPlannerNode:

    @patch("app.agent.workflow.get_llm")
    def test_single_skill_skips_planning(self, mock_llm):
        from app.agent.workflow import planner
        state = {
            "skills_to_execute": ["product_skill"],
            "user_input": "分析商品",
        }
        result = planner(state)
        assert result["execution_plan"] is None
        mock_llm.assert_not_called()

    @patch("app.agent.workflow.get_llm")
    def test_empty_skills_skips_planning(self, mock_llm):
        from app.agent.workflow import planner
        state = {"skills_to_execute": [], "user_input": "test"}
        result = planner(state)
        assert result["execution_plan"] is None

    @patch("app.agent.workflow._planner_llm_call")
    @patch("app.agent.workflow.get_llm")
    def test_multi_skill_creates_plan(self, mock_get_llm, mock_call_llm):
        from app.agent.workflow import planner
        mock_llm = MagicMock()
        mock_get_llm.return_value = mock_llm

        plan_json = json.dumps({
            "steps": [
                {"skill": "inventory_skill", "args": {"user_input": "查库存"}},
                {"skill": "report_skill", "args": {"user_input": "生成报告，参考{prev_output}"}},
            ]
        })
        mock_response = MagicMock()
        mock_response.content = plan_json
        mock_call_llm.return_value = mock_response

        state = {
            "skills_to_execute": ["inventory_skill", "report_skill"],
            "user_input": "查库存并生成报告",
        }
        result = planner(state)
        assert result["execution_plan"] is not None
        assert len(result["execution_plan"]) == 2
        assert result["execution_plan"][0]["skill"] == "inventory_skill"

    @patch("app.agent.workflow._planner_llm_call")
    @patch("app.agent.workflow.get_llm")
    def test_planner_filters_invalid_skills(self, mock_get_llm, mock_call_llm):
        from app.agent.workflow import planner
        mock_llm = MagicMock()
        mock_get_llm.return_value = mock_llm

        plan_json = json.dumps({
            "steps": [
                {"skill": "inventory_skill", "args": {"user_input": "查库存"}},
                {"skill": "nonexistent_skill", "args": {"user_input": "bad"}},
            ]
        })
        mock_response = MagicMock()
        mock_response.content = plan_json
        mock_call_llm.return_value = mock_response

        state = {
            "skills_to_execute": ["inventory_skill", "report_skill"],
            "user_input": "test",
        }
        result = planner(state)
        assert len(result["execution_plan"]) == 1
        assert result["execution_plan"][0]["skill"] == "inventory_skill"

    @patch("app.agent.workflow._planner_llm_call")
    @patch("app.agent.workflow.get_llm")
    def test_planner_llm_error_fallback(self, mock_get_llm, mock_call_llm):
        from app.agent.workflow import planner
        mock_get_llm.return_value = MagicMock()
        mock_call_llm.side_effect = RuntimeError("timeout")

        state = {
            "skills_to_execute": ["a", "b"],
            "user_input": "test",
        }
        result = planner(state)
        assert result["execution_plan"] is None


class TestSkillExecutorPlanMode:

    @patch("app.agent.workflow._execute_single_skill")
    def test_plan_execute_sequential(self, mock_exec):
        from app.agent.workflow import skill_executor
        mock_exec.return_value = {"type": "text", "data": "result"}

        state = {
            "execution_plan": [
                {"skill": "inventory_skill", "args": {"user_input": "查库存"}},
                {"skill": "report_skill", "args": {"user_input": "生成报告"}},
            ],
            "tool_result": {},
            "skills_to_execute": ["inventory_skill", "report_skill"],
            "conversation_id": "test",
        }
        result = skill_executor(state)
        assert len(result["skill_results"]) == 2
        assert mock_exec.call_count == 2

    @patch("app.agent.workflow._execute_single_skill")
    def test_plan_execute_dependency_passing(self, mock_exec):
        from app.agent.workflow import skill_executor
        mock_exec.return_value = {"type": "text", "data": "库存数据: A=100"}

        state = {
            "execution_plan": [
                {"skill": "inventory_skill", "args": {"user_input": "查库存"}},
                {"skill": "report_skill", "args": {"user_input": "基于{prev_output}生成报告"}},
            ],
            "tool_result": {},
            "skills_to_execute": ["inventory_skill", "report_skill"],
            "conversation_id": "test",
        }
        skill_executor(state)
        # 第二次调用应包含前序输出
        second_call_args = mock_exec.call_args_list[1]
        step_input = second_call_args[0][1]  # user_input arg
        assert "库存数据" in step_input

    @patch("app.agent.workflow._execute_single_skill")
    def test_no_plan_uses_sequential_mode(self, mock_exec):
        from app.agent.workflow import skill_executor
        mock_exec.return_value = {"type": "text", "data": "ok"}

        state = {
            "execution_plan": None,
            "tool_result": {"user_input": "分析商品", "skill": "product_skill"},
            "skills_to_execute": ["product_skill"],
            "conversation_id": "test",
        }
        result = skill_executor(state)
        assert len(result["skill_results"]) == 1
        assert mock_exec.call_count == 1


class TestGraphStructure:

    def test_planner_in_graph(self):
        import inspect
        import app.agent.workflow as wf
        source = inspect.getsource(wf)
        assert 'graph.add_node("planner", planner)' in source
        assert 'graph.add_edge("router", "planner")' in source
        assert 'graph.add_edge("planner", "skill_executor")' in source

    def test_state_has_execution_plan(self):
        from app.agent.state import AgentState
        annotations = AgentState.__annotations__
        assert "execution_plan" in annotations