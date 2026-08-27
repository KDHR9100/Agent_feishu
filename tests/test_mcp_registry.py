"""任务4: MCP动态工具注册 单元测试"""
import os
import sys
import json
import tempfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestSkillsManifest:

    def test_manifest_exists_and_valid(self):
        manifest_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "skills_manifest.json",
        )
        assert os.path.exists(manifest_path)
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "skills" in data
        # 删除 content_skill 后共 13 个技能
        assert len(data["skills"]) == 13

    def test_all_skills_have_required_fields(self):
        manifest_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "skills_manifest.json",
        )
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for skill in data["skills"]:
            assert "name" in skill
            assert "description" in skill
            assert "keywords" in skill
            assert isinstance(skill["keywords"], list)
            assert len(skill["keywords"]) > 0


class TestSkillRegistry:

    def test_registry_loads_skills(self):
        from app.mcp_server.registry import SkillRegistry
        reg = SkillRegistry()
        assert reg.skill_count == 13

    def test_list_tools_returns_all(self):
        from app.mcp_server.registry import SkillRegistry
        reg = SkillRegistry()
        tools = reg.list_tools()
        assert len(tools) == 13
        names = {t["name"] for t in tools}
        assert "product_skill" in names
        assert "ads_skill" in names
        assert "help_skill" in names

    def test_get_keyword_rules(self):
        from app.mcp_server.registry import SkillRegistry
        reg = SkillRegistry()
        rules = reg.get_keyword_rules()
        assert "product_skill" in rules
        assert "广告" in rules["ads_skill"]
        assert "库存" in rules["inventory_skill"]
        assert "listing" in rules

    def test_get_skill_by_name(self):
        from app.mcp_server.registry import SkillRegistry
        reg = SkillRegistry()
        skill = reg.get_skill("seo_skill")
        assert skill is not None
        assert skill["name"] == "seo_skill"
        assert "SEO" in skill["keywords"]

    def test_get_nonexistent_skill(self):
        from app.mcp_server.registry import SkillRegistry
        reg = SkillRegistry()
        assert reg.get_skill("nonexistent_skill") is None

    def test_get_all_skill_names(self):
        from app.mcp_server.registry import SkillRegistry
        reg = SkillRegistry()
        names = reg.get_all_skill_names()
        assert len(names) == 13
        assert "data_analysis_skill" in names
        assert "pricing_skill" in names
        assert "listing" in names

    def test_register_skill_runtime(self):
        from app.mcp_server.registry import SkillRegistry
        reg = SkillRegistry()
        initial_count = reg.skill_count
        reg.register_skill({
            "name": "new_skill",
            "description": "A new test skill",
            "keywords": ["test", "new"],
        })
        assert reg.skill_count == initial_count + 1
        assert reg.get_skill("new_skill") is not None
        assert "test" in reg.get_keyword_rules()["new_skill"]

    def test_reload(self):
        from app.mcp_server.registry import SkillRegistry
        reg = SkillRegistry()
        reg.register_skill({"name": "temp_skill", "keywords": []})
        assert reg.skill_count == 14
        reg.reload()
        assert reg.skill_count == 13  # reload resets to manifest

    def test_invalid_manifest_graceful(self):
        from app.mcp_server.registry import SkillRegistry
        reg = SkillRegistry(manifest_path="/nonexistent/path.json")
        assert reg.skill_count == 0
        assert reg.get_keyword_rules() == {}


class TestRouterDynamicLoading:

    def test_router_keyword_rules_from_manifest(self):
        from app.agent.router import KEYWORD_RULES
        assert "product_skill" in KEYWORD_RULES
        assert "ads_skill" in KEYWORD_RULES
        assert len(KEYWORD_RULES) == 13

    def test_router_tools_count(self):
        from app.agent.router import _build_tools
        # 删除 content_skill 后共 13 个
        assert len(_build_tools()) == 13

    def test_router_keyword_fallback(self):
        from app.agent.router import keyword_fallback
        result = keyword_fallback("帮我分析一下商品销量")
        assert result == ["product_skill"]

    def test_router_keyword_fallback_ads(self):
        from app.agent.router import keyword_fallback
        result = keyword_fallback("广告投放ROI怎么样")
        assert result == ["ads_skill"]

    def test_router_keyword_fallback_no_match(self):
        from app.agent.router import keyword_fallback
        result = keyword_fallback("今天天气怎么样")
        assert result == []

    def test_router_tools_have_correct_names(self):
        from app.agent.router import _build_tools
        tool_names = {t.name for t in _build_tools()}
        assert "product_skill" in tool_names
        assert "inventory_skill" in tool_names
        assert "support_skill" in tool_names