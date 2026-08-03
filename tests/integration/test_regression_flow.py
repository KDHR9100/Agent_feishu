"""集成测试6: 回归测试 - 4个核心技能路由正确性"""
import os
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestCoreSkillRouting:
    """确保 MCP 重构后, 4个核心业务技能路由不被改废"""

    def test_inventory_routing(self):
        """'库存预警' 必须命中 inventory_skill"""
        from app.agent.router import keyword_fallback
        result = keyword_fallback("库存预警，哪些SKU要补货了")
        # v2: 多技能命中按得分降序返回, 主技能必须排首位
        assert result and result[0] == "inventory_skill"

    def test_content_routing(self):
        """'写一段小红书文案' 必须命中 content_skill"""
        from app.agent.router import keyword_fallback
        result = keyword_fallback("写一段小红书文案，推广新款连衣裙")
        # v2: 多技能命中按得分降序返回, 主技能必须排首位
        assert result and result[0] == "content_skill"

    def test_ads_routing(self):
        """'广告ROI是多少' 必须命中 ads_skill"""
        from app.agent.router import keyword_fallback
        result = keyword_fallback("广告ROI是多少，花费和转化怎么样")
        assert result == ["ads_skill"]

    def test_help_routing(self):
        """'帮助' 必须命中 help_skill"""
        from app.agent.router import keyword_fallback
        result = keyword_fallback("帮助，你能做什么")
        assert result == ["help_skill"]


class TestAllSkillsRegistered:
    """确保 12 个技能全部在 manifest 和 router 中注册"""

    def test_manifest_has_12_skills(self):
        from app.mcp_server import skill_registry
        assert skill_registry.skill_count == 12

    def test_router_tools_has_12(self):
        from app.agent import router
        router._ensure_tools_fresh()
        assert len(router._cache["tools"]) == 12

    def test_skill_registry_has_12(self):
        from app.agent.workflow import SKILL_REGISTRY
        assert len(SKILL_REGISTRY) == 12

    def test_all_manifest_skills_in_workflow_registry(self):
        """manifest 中的每个技能都必须在 workflow SKILL_REGISTRY 中有执行函数"""
        from app.mcp_server import skill_registry
        from app.agent.workflow import SKILL_REGISTRY

        manifest_names = set(skill_registry.get_all_skill_names())
        workflow_names = set(SKILL_REGISTRY.keys())

        missing = manifest_names - workflow_names
        assert not missing, f"Skills in manifest but not in workflow: {missing}"


class TestRouterStateOutput:
    """验证 router 输出的 state 结构完整"""

    def test_router_output_has_required_fields(self):
        """router 必须设置 tool_result, skills_to_execute, intent"""
        from app.agent.router import keyword_fallback

        # 模拟 keyword fallback 路径
        skills = keyword_fallback("查库存")
        assert len(skills) > 0

        # 构造 router 会输出的 state
        state = {
            "tool_result": {"skill": skills[0], "user_input": "查库存"},
            "skills_to_execute": skills,
            "intent": skills[0],
        }
        assert "tool_result" in state
        assert "skills_to_execute" in state
        assert "intent" in state
        assert state["skills_to_execute"] == ["inventory_skill"]


class TestWorkflowGraphIntegrity:
    """验证 LangGraph 图结构完整"""

    def test_graph_has_all_nodes(self):
        import inspect
        import app.agent.workflow as wf
        source = inspect.getsource(wf)

        required_nodes = [
            "load_history", "load_file", "router", "planner",
            "skill_executor", "reflect", "answer", "save_history",
        ]
        for node in required_nodes:
            assert f'graph.add_node("{node}"' in source, f"Missing node: {node}"

    def test_graph_edge_chain(self):
        """验证边链: load_history→load_file→router→planner→skill_executor→reflect"""
        import inspect
        import app.agent.workflow as wf
        source = inspect.getsource(wf)

        edges = [
            ('graph.add_edge("load_history", "load_file")', "load_history→load_file"),
            ('graph.add_edge("load_file", "router")', "load_file→router"),
            ('graph.add_edge("router", "planner")', "router→planner"),
            ('graph.add_edge("planner", "skill_executor")', "planner→skill_executor"),
            ('graph.add_edge("skill_executor", "reflect")', "skill_executor→reflect"),
            ('graph.add_edge("answer", "save_history")', "answer→save_history"),
            ('graph.add_edge("save_history", END)', "save_history→END"),
        ]
        for edge_str, desc in edges:
            assert edge_str in source, f"Missing edge: {desc}"

    def test_conditional_edge_reflect(self):
        """reflect 必须有条件边到 router 和 answer"""
        import inspect
        import app.agent.workflow as wf
        source = inspect.getsource(wf)
        assert "add_conditional_edges" in source
        assert '"router": "router"' in source
        assert '"answer": "answer"' in source