"""测试 Agent 工作流核心组件"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class TestSkillRegistry:
    def test_all_router_tools_registered(self):
        from app.agent.router import _build_tools
        from app.agent.workflow import SKILL_REGISTRY
        tools = _build_tools()
        router_skill_names = set()
        for tool in tools:
            router_skill_names.add(tool.name)
        for skill_name in router_skill_names:
            assert skill_name in SKILL_REGISTRY, f"Skill '{skill_name}' not in SKILL_REGISTRY"

    def test_registry_has_expected_skills(self):
        from app.agent.workflow import SKILL_REGISTRY
        expected = {"product_skill", "ads_skill", "help_skill",
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


class TestExtractTextFromResult:
    def test_report_skill_summary_extracted_not_dict_repr(self):
        """B4 回归: report_skill 无数据分支的 summary 必须以自然语言输出,
        不能退化为 {'summary': ..., 'success': False} 的 dict repr"""
        from app.agent.workflow import _extract_text_from_result
        result = {
            "type": "report_generation",
            "data": {
                "summary": "抱歉，本周暂无可用于生成运营报告的数据。",
                "report_file": "",
                "success": False,
                "no_data": True,
            },
        }
        text = _extract_text_from_result(result)
        assert text == "抱歉，本周暂无可用于生成运营报告的数据。"
        assert "{" not in text and "success" not in text

    def test_report_skill_with_file_appends_path(self):
        from app.agent.workflow import _extract_text_from_result
        result = {
            "type": "report_generation",
            "data": {"summary": "报告摘要", "report_file": "reports/report_x.md",
                     "success": True},
        }
        text = _extract_text_from_result(result)
        assert text.startswith("报告摘要")
        assert "reports/report_x.md" in text

class TestDerivedNumberHonestyPrompts:
    """缺陷档案 #3: 推导数字泛滥——综合回答/数据分析允许推导但必须标注算式"""

    def test_summarization_prompt_requires_derivation_formula(self):
        from app.agent.workflow import SUMMARIZATION_PROMPT_TEMPLATE
        assert "推导值" in SUMMARIZATION_PROMPT_TEMPLATE
        assert "简式" in SUMMARIZATION_PROMPT_TEMPLATE
        # 只允许"出处数字"与"带算式推导值"两类, 杜绝凭空数字
        assert "不得出现任何数字" in SUMMARIZATION_PROMPT_TEMPLATE

    def test_data_analysis_prompt_allows_labeled_derivation(self):
        from app.skills.data_analysis_skill import DATA_ANALYSIS_SYSTEM_PROMPT
        assert "推导值" in DATA_ANALYSIS_SYSTEM_PROMPT
        assert "推导" in DATA_ANALYSIS_SYSTEM_PROMPT and "简式" in DATA_ANALYSIS_SYSTEM_PROMPT

    def test_product_and_ads_prompts_require_derivation_label(self):
        """单技能直出路径(商品/广告分析)同样受推导值规则约束——
        全量 run-20260910-230630 实测: ads_manager 幻觉 0.00 正因该路径漏覆盖"""
        from app.prompts import ADS_ANALYSIS_PROMPT, PRODUCT_ANALYSIS_PROMPT
        for prompt in (PRODUCT_ANALYSIS_PROMPT, ADS_ANALYSIS_PROMPT):
            assert "推导值" in prompt
            assert "经验假设值" in prompt

    def test_file_analysis_prompt_requires_derivation_label(self):
        import inspect
        from app.skills import file_analysis_skill as fas
        assert "推导值" in inspect.getsource(fas)  # 文件分析内联 system prompt 同受约束

    def test_pricing_skill_passes_history_from_call_site(self):
        """统一调用入口: pricing_skill 技能收到会话历史(其余技能不受影响)"""
        from app.agent.workflow import _call_skill
        captured = {}

        def _fake_pricing(user_input, file_path, file_content, tool_result, history=None):
            captured["history"] = history
            return {"type": "analysis", "data": {"analysis": "ok"}}

        def _fake_other(user_input, file_path, file_content, tool_result):
            captured["other_args"] = 4
            return {"type": "analysis", "data": {"analysis": "ok"}}

        import app.agent.workflow as wf
        orig = dict(wf.SKILL_REGISTRY)
        try:
            wf.SKILL_REGISTRY["pricing_skill"] = _fake_pricing
            wf.SKILL_REGISTRY["product_skill"] = _fake_other
            _call_skill("pricing_skill", "q", None, None, None,
                        {"history": [{"role": "user", "content": "SKU001"}]})
            _call_skill("product_skill", "q", None, None, None, {"history": []})
        finally:
            wf.SKILL_REGISTRY.clear()
            wf.SKILL_REGISTRY.update(orig)
        assert captured["history"] == [{"role": "user", "content": "SKU001"}]
        assert captured["other_args"] == 4
