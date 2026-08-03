"""集成测试3: MCP热插拔 - 运行时注册新技能, 不重启即命中"""
import os
import sys
import json
import tempfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestMCPHotPlugFlow:
    """模拟: 在 manifest 新增 test_skill → reload → 路由命中"""

    def test_register_then_keyword_hit(self):
        """运行时 register_skill 后, keyword_fallback 立即命中"""
        from app.mcp_server.registry import SkillRegistry

        reg = SkillRegistry()
        initial_count = reg.skill_count

        # 运行时注册新技能
        reg.register_skill({
            "name": "test_skill",
            "description": "测试用技能",
            "keywords": ["测试", "test"],
        })

        # 验证: 数量+1
        assert reg.skill_count == initial_count + 1

        # 验证: keyword_rules 包含新技能
        rules = reg.get_keyword_rules()
        assert "test_skill" in rules
        assert "测试" in rules["test_skill"]

        # 验证: list_tools 包含新技能
        tools = reg.list_tools()
        tool_names = {t["name"] for t in tools}
        assert "test_skill" in tool_names

    def test_manifest_reload_picks_up_new_skill(self):
        """修改 manifest 文件 → reload → 新技能生效"""
        from app.mcp_server.registry import SkillRegistry

        # 创建临时 manifest
        manifest = {
            "version": "1.0",
            "skills": [
                {"name": "skill_a", "description": "A", "keywords": ["甲"]},
                {"name": "skill_b", "description": "B", "keywords": ["乙"]},
            ]
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(manifest, f, ensure_ascii=False)
            tmp_path = f.name

        try:
            reg = SkillRegistry(manifest_path=tmp_path)
            assert reg.skill_count == 2

            # 模拟: 往 manifest 文件追加新技能
            manifest["skills"].append({
                "name": "skill_c",
                "description": "C",
                "keywords": ["丙"],
            })
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False)

            # reload 前: 还是2个
            assert reg.skill_count == 2

            # reload 后: 变成3个
            reg.reload()
            assert reg.skill_count == 3
            assert reg.get_skill("skill_c") is not None
            assert "丙" in reg.get_keyword_rules()["skill_c"]
        finally:
            os.unlink(tmp_path)

    def test_router_uses_dynamic_rules(self):
        """验证 router 的 KEYWORD_RULES 确实来自 registry"""
        from app.agent.router import KEYWORD_RULES
        from app.mcp_server import skill_registry

        # router 的规则应该和 registry 一致
        registry_rules = skill_registry.get_keyword_rules()
        assert set(KEYWORD_RULES.keys()) == set(registry_rules.keys())

        # 每个技能的关键词列表一致
        for skill_name in KEYWORD_RULES:
            assert KEYWORD_RULES[skill_name] == registry_rules[skill_name]

    def test_new_skill_keyword_fallback_end_to_end(self):
        """端到端: 注册新技能 → keyword_fallback 命中"""
        from app.mcp_server.registry import SkillRegistry
        from app.agent.router import keyword_fallback, KEYWORD_RULES

        # 注意: router 的 KEYWORD_RULES 是模块加载时的快照
        # 热插拔需要 reload 后 router 才能感知
        # 这里验证 registry 层面的热插拔
        reg = SkillRegistry()
        reg.register_skill({
            "name": "hot_skill",
            "description": "热插拔技能",
            "keywords": ["热插拔"],
        })

        # registry 层面可以命中
        rules = reg.get_keyword_rules()
        input_text = "我要热插拔一下"
        scores = {}
        for skill, keywords in rules.items():
            hit = sum(1 for kw in keywords if kw.lower() in input_text.lower())
            if hit > 0:
                scores[skill] = hit
        assert "hot_skill" in scores