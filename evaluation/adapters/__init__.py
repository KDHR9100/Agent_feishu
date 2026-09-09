"""评测系统与 FeishuAgent 的对接层（mock 替身 / 真实进程内适配器）。"""

from evaluation.adapters.agent_adapter import (
    ATTACKS_PATH,
    FIXTURES_DATA_DIR,
    SKILLS_MANIFEST_PATH,
    AgentAdapter,
    MockFeishuAgent,
    RealFeishuAgent,
    has_pricing_directive,
    load_attacks,
    load_skills_manifest,
    manifest_skill_names,
)

__all__ = [
    "ATTACKS_PATH",
    "FIXTURES_DATA_DIR",
    "SKILLS_MANIFEST_PATH",
    "AgentAdapter",
    "MockFeishuAgent",
    "RealFeishuAgent",
    "has_pricing_directive",
    "load_attacks",
    "load_skills_manifest",
    "manifest_skill_names",
]
