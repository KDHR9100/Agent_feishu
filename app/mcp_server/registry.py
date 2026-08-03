"""MCP 动态工具注册中心 - 从 skills_manifest.json 加载技能定义"""
import json
import logging
import os
from typing import Dict, List, Optional, Any

logger = logging.getLogger("mcp_registry")

# manifest 文件路径(项目根目录)
_MANIFEST_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "skills_manifest.json",
)


class SkillRegistry:
    """技能注册中心: 从 JSON manifest 动态加载技能元数据"""

    def __init__(self, manifest_path: str = _MANIFEST_PATH):
        self._manifest_path = manifest_path
        self._skills: List[Dict[str, Any]] = []
        self._keyword_rules: Dict[str, List[str]] = {}
        self._skill_map: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self):
        """从 manifest 文件加载技能定义"""
        try:
            with open(self._manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._skills = data.get("skills", [])
            self._skill_map = {s["name"]: s for s in self._skills}
            self._keyword_rules = {
                s["name"]: s.get("keywords", []) for s in self._skills
            }
            logger.info(
                "[mcp_registry] loaded %d skills from %s"
                % (len(self._skills), self._manifest_path)
            )
        except Exception as e:
            logger.error("[mcp_registry] failed to load manifest: %s", e)
            self._skills = []
            self._keyword_rules = {}
            self._skill_map = {}

    def reload(self):
        """热重载: 运行时重新读取 manifest(支持新增技能不重启)"""
        logger.info("[mcp_registry] reloading manifest...")
        self._load()

    def list_tools(self) -> List[Dict[str, Any]]:
        """MCP list_tools 适配: 返回所有技能的元数据"""
        return [
            {
                "name": s["name"],
                "description": s.get("description", ""),
                "keywords": s.get("keywords", []),
            }
            for s in self._skills
        ]

    def get_keyword_rules(self) -> Dict[str, List[str]]:
        """返回关键词规则表(替代硬编码的 KEYWORD_RULES)"""
        return self._keyword_rules.copy()

    def get_skill(self, name: str) -> Optional[Dict[str, Any]]:
        """按名称获取技能定义"""
        return self._skill_map.get(name)

    def get_all_skill_names(self) -> List[str]:
        """返回所有技能名称列表"""
        return [s["name"] for s in self._skills]

    def register_skill(self, skill_def: Dict[str, Any]):
        """运行时动态注册新技能(写入内存, 不持久化)"""
        name = skill_def.get("name")
        if not name:
            logger.warning("[mcp_registry] register_skill: missing name")
            return
        # 更新或新增
        if name in self._skill_map:
            self._skill_map[name].update(skill_def)
        else:
            self._skills.append(skill_def)
            self._skill_map[name] = skill_def
        self._keyword_rules[name] = skill_def.get("keywords", [])
        logger.info("[mcp_registry] registered skill: %s", name)

    @property
    def skill_count(self) -> int:
        return len(self._skills)


# 全局单例
skill_registry = SkillRegistry()