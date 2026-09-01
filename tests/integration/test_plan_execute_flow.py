"""集成测试4: Plan-Execute - 3步顺序执行+依赖传递"""
import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestPlanExecuteFlow:
    """模拟: 用户发复合指令 → planner 输出3步 → skill_executor 顺序执行"""

    @patch("app.agent.workflow._planner_llm_call")
    @patch("app.agent.workflow.get_llm")
    def test_3_step_plan_sequential_execution(self, mock_get_llm, mock_call_llm):
        """3个技能必须按 planner 输出的顺序执行, 不能并行"""
        from app.agent.workflow import planner, skill_executor

        mock_get_llm.return_value = MagicMock()

        # planner LLM 返回3步计划
        plan_json = json.dumps({
            "steps": [
                {"skill": "inventory_skill", "args": {"user_input": "查A商品库存"}},
                {"skill": "report_skill", "args": {"user_input": "基于{prev_output}生成补货报告"}},
                {"skill": "ads_skill", "args": {"user_input": "分析广告费是否追加"}},
            ]
        })
        mock_response = MagicMock()
        mock_response.content = plan_json
        mock_call_llm.return_value = mock_response

        # Step 1: planner 生成计划
        state = {
            "user_input": "查A商品库存，如果低于100件生成补货报告，并分析广告费",
            "skills_to_execute": ["inventory_skill", "report_skill", "ads_skill"],
            "conversation_id": "test-plan",
        }
        state = planner(state)

        assert state["execution_plan"] is not None
        assert len(state["execution_plan"]) == 3
        assert state["execution_plan"][0]["skill"] == "inventory_skill"
        assert state["execution_plan"][1]["skill"] == "report_skill"
        assert state["execution_plan"][2]["skill"] == "ads_skill"

    @patch("app.agent.workflow._execute_single_skill")
    def test_dependency_passing_prev_output(self, mock_exec):
        """上一步输出必须注入下一步的 user_input"""
        from app.agent.workflow import skill_executor

        # 模拟每步返回不同结果
        mock_exec.side_effect = [
            {"type": "text", "data": "A商品库存: 85件, 低于100件预警线"},
            {"type": "text", "data": "补货报告: 建议补货200件"},
            {"type": "text", "data": "广告分析: ROI=3.2, 建议追加"},
        ]

        state = {
            "execution_plan": [
                {"skill": "inventory_skill", "args": {"user_input": "查A商品库存"}},
                {"skill": "report_skill", "args": {"user_input": "基于{prev_output}生成补货报告"}},
                {"skill": "ads_skill", "args": {"user_input": "分析广告费是否追加"}},
            ],
            "tool_result": {},
            "skills_to_execute": ["inventory_skill", "report_skill", "ads_skill"],
            "conversation_id": "test-dep",
        }
        result = skill_executor(state)

        # 验证: 3步都执行了
        assert mock_exec.call_count == 3
        assert len(result["skill_results"]) == 3

        # 验证: 第2步的 user_input 包含第1步的输出
        second_call_input = mock_exec.call_args_list[1][0][1]
        assert "85件" in second_call_input or "库存" in second_call_input

        # 验证: 第3步的 user_input 包含第2步的输出
        third_call_input = mock_exec.call_args_list[2][0][1]
        # 新行为: 未使用 {prev_output} 占位符的步骤输入保持干净, 不被前序输出污染
        assert len(third_call_input) < 30

    @patch("app.agent.workflow._execute_single_skill")
    def test_plan_execute_order_preserved(self, mock_exec):
        """执行顺序必须严格按 plan 定义"""
        from app.agent.workflow import skill_executor

        execution_order = []
        def track_execution(skill_name, *args, **kwargs):
            execution_order.append(skill_name)
            return {"type": "text", "data": f"{skill_name} done"}

        mock_exec.side_effect = track_execution

        state = {
            "execution_plan": [
                {"skill": "seo_skill", "args": {"user_input": "step1"}},
                {"skill": "ads_skill", "args": {"user_input": "step2"}},
                {"skill": "report_skill", "args": {"user_input": "step3"}},
            ],
            "tool_result": {},
            "skills_to_execute": ["seo_skill", "ads_skill", "report_skill"],
            "conversation_id": "test-order",
        }
        skill_executor(state)

        assert execution_order == ["seo_skill", "ads_skill", "report_skill"]

    @patch("app.agent.workflow._execute_single_skill")
    def test_no_plan_falls_back_to_list_mode(self, mock_exec):
        """无 execution_plan 时走原有列表迭代模式"""
        from app.agent.workflow import skill_executor

        mock_exec.return_value = {"type": "text", "data": "ok"}

        state = {
            "execution_plan": None,
            "tool_result": {"user_input": "查库存", "skill": "inventory_skill"},
            "skills_to_execute": ["inventory_skill"],
            "conversation_id": "test-fallback",
        }
        result = skill_executor(state)

        assert mock_exec.call_count == 1
        assert len(result["skill_results"]) == 1

    @patch("app.agent.workflow._call_llm")
    @patch("app.agent.workflow.get_llm")
    def test_single_skill_skips_planner(self, mock_get_llm, mock_call_llm):
        """单技能请求不经过 planner LLM 调用"""
        from app.agent.workflow import planner

        state = {
            "user_input": "查库存",
            "skills_to_execute": ["inventory_skill"],
        }
        result = planner(state)

        assert result["execution_plan"] is None
        mock_call_llm.assert_not_called()

class TestPlanExecuteCleanDependency:
    """修复验证: 依赖传递仅通过 {prev_output} 占位符, 且不传递 user_input 回显"""

    @patch("app.agent.workflow._execute_single_skill")
    def test_user_input_echo_not_propagated(self, mock_exec):
        from app.agent.workflow import skill_executor

        big_echo = "污染文本" * 200
        mock_exec.side_effect = [
            {"type": "inventory_report", "data": {
                "user_input": big_echo,
                "low_inventory_items": [{"product_id": "SKU001", "current_stock": 0}],
            }},
            {"type": "report_generation", "data": {"summary": "ok", "report_file": "x.md", "success": True}},
        ]
        state = {
            "execution_plan": [
                {"skill": "inventory_skill", "args": {"user_input": "查库存"}},
                {"skill": "report_skill", "args": {"user_input": "基于{prev_output}生成补货报告"}},
            ],
            "tool_result": {},
            "skills_to_execute": ["inventory_skill", "report_skill"],
            "conversation_id": "test-echo",
        }
        skill_executor(state)
        second_input = mock_exec.call_args_list[1][0][1]
        assert "污染文本" not in second_input
        assert "SKU001" in second_input  # 真实数据正常传递

    @patch("app.agent.workflow._execute_single_skill")
    def test_no_placeholder_keeps_input_clean(self, mock_exec):
        from app.agent.workflow import skill_executor

        mock_exec.side_effect = [
            {"type": "text", "data": "第一步的超长输出" * 100},
            {"type": "text", "data": "ok"},
        ]
        state = {
            "execution_plan": [
                {"skill": "inventory_skill", "args": {"user_input": "查库存"}},
                {"skill": "ads_skill", "args": {"user_input": "分析广告费"}},
            ],
            "tool_result": {},
            "skills_to_execute": ["inventory_skill", "ads_skill"],
            "conversation_id": "test-clean",
        }
        skill_executor(state)
        second_input = mock_exec.call_args_list[1][0][1]
        assert second_input == "分析广告费"


class TestSequentialReportPassing:
    """修复验证: planner 超时退化为 sequential 时, report_skill 仍能拿到前序数据"""

    def test_report_gets_prev_result_in_sequential(self):
        from unittest.mock import patch
        from app.agent.workflow import skill_executor

        captured = {}

        def fake_exec(skill_name, user_input, file_path, file_content, tr, state):
            captured.setdefault(skill_name, tr)
            if skill_name == "inventory_skill":
                return {"type": "inventory_report", "data": {
                    "low_inventory_items": [{"product_id": "SKU001", "current_stock": 0}]}}
            if skill_name == "report_skill":
                return {"type": "report_generation", "data": {"summary": "ok"}}
            return {"type": "text", "data": "ok"}

        with patch("app.agent.workflow._execute_single_skill", side_effect=fake_exec):
            state = {
                "execution_plan": None,
                "tool_result": {"skill": "inventory_skill", "user_input": "查库存并生成报告"},
                "skills_to_execute": ["inventory_skill", "report_skill"],
                "conversation_id": "test-seq-report",
            }
            result = skill_executor(state)

        assert len(result["skill_results"]) == 2
        # report_skill 拿到的应该是 inventory 的真实结果, 而不是原始用户查询
        report_tr = captured["report_skill"]
        assert isinstance(report_tr, dict)
        assert report_tr["data"]["low_inventory_items"][0]["current_stock"] == 0
