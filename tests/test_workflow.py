"""测试 Agent 工作流核心组件"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class TestSkillRegistry:
    def test_all_router_tools_registered(self):
        from app.agent.router import tools
        from app.agent.workflow import SKILL_REGISTRY
        router_skill_names = set()
        for tool in tools:
            router_skill_names.add(tool.name)
        for skill_name in router_skill_names:
            assert skill_name in SKILL_REGISTRY, f"Skill '{skill_name}' not in SKILL_REGISTRY"

    def test_registry_has_expected_skills(self):
        from app.agent.workflow import SKILL_REGISTRY
        expected = {"product_skill", "ads_skill", "content_skill", "help_skill",
                    "file_analysis_skill", "inventory_skill", "competitor_skill",
                    "report_skill", "rag_skill"}
        for skill in expected:
            assert skill in SKILL_REGISTRY, f"Expected '{skill}' not in registry"

    def test_registry_runners_are_callable(self):
        from app.agent.workflow import SKILL_REGISTRY
        for name, runner in SKILL_REGISTRY.items():
            assert callable(runner), f"Runner for '{name}' is not callable"

class TestAgentState:
    def test_state_has_required_fields(self):
        from app.agent.state import AgentState
        import typing
        annotations = typing.get_type_hints(AgentState)
        required = {"user_input", "conversation_id", "history", "tool_result",
                    "answer", "intent", "file_path", "file_content",
                    "skills_to_execute", "skill_results", "retry_count",
                    "reflect_feedback", "reflect_decision"}
        for field in required:
            assert field in annotations, f"AgentState missing: {field}"

    def test_max_retries_defined(self):
        from app.agent.state import MAX_RETRIES
        assert isinstance(MAX_RETRIES, int)
        assert MAX_RETRIES >= 1

class TestReflectSkipSkills:
    def test_file_and_rag_skip_reflect(self):
        from app.agent.workflow import reflect
        state = {"skills_to_execute": ["file_analysis_skill"],
                 "skill_results": [{"skill": "file_analysis_skill", "result": {"data": "test"}}],
                 "retry_count": 0, "user_input": "分析这个文件"}
        result = reflect(state)
        assert result["reflect_decision"] == "sufficient"

        state2 = {"skills_to_execute": ["rag_skill"],
                  "skill_results": [{"skill": "rag_skill", "result": {"data": {"analysis": "test"}}}],
                  "retry_count": 0, "user_input": "平台佣金规则"}
        result2 = reflect(state2)
        assert result2["reflect_decision"] == "sufficient"