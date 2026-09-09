"""Persona 加载器：YAML → Pydantic 校验（fail-fast）。"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import structlog
import yaml

from evaluation.adapters.agent_adapter import manifest_skill_names
from evaluation.personas.base_persona import BasePersona

logger = structlog.get_logger(__name__)

#: 默认画像资产文件
DEFAULT_PERSONAS_PATH = Path(__file__).resolve().parent / "ecommerce_personas.yaml"


def load_personas(
    path: Optional[Path] = None,
    validate_tools: bool = True,
) -> List[BasePersona]:
    """加载画像 YAML 并做 Pydantic 校验。

    - 重复 persona_id 直接报错；
    - ``validate_tools=True`` 时校验 expected_tools ⊆ skills_manifest 技能名
      （对接 FeishuAgent 现有清单，拼错当场失败而不是跑到第 7 轮才崩）。
    """

    personas_path = Path(path) if path else DEFAULT_PERSONAS_PATH
    with open(personas_path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    if not isinstance(raw, list) or not raw:
        raise ValueError(f"画像文件必须是非空 YAML 列表: {personas_path}")

    known_tools = manifest_skill_names() if validate_tools else None
    personas: List[BasePersona] = []
    seen_ids: set = set()
    for idx, item in enumerate(raw):
        try:
            persona = BasePersona.model_validate(item)
        except Exception as exc:  # noqa: BLE001 - 统一转换为带定位的错误
            raise ValueError(f"第 {idx + 1} 个画像校验失败 ({personas_path}): {exc}") from exc
        if persona.persona_id in seen_ids:
            raise ValueError(f"重复的 persona_id: {persona.persona_id}")
        seen_ids.add(persona.persona_id)
        if known_tools is not None:
            unknown = set(persona.expected_tools) - known_tools
            if unknown:
                raise ValueError(
                    f"画像 {persona.persona_id} 引用了 manifest 不存在的技能: {sorted(unknown)}"
                )
        personas.append(persona)

    logger.info("personas_loaded", count=len(personas), file=str(personas_path))
    return personas


def get_persona(persona_id: str, path: Optional[Path] = None) -> BasePersona:
    """按 id 取单个画像（CLI --persona 单跑用）。"""

    for persona in load_personas(path):
        if persona.persona_id == persona_id:
            return persona
    raise ValueError(f"persona 不存在: {persona_id}（可用: {DEFAULT_PERSONAS_PATH}）")
