"""Persona 层测试。"""

from pathlib import Path

import pytest
import yaml

from evaluation.personas import DEFAULT_PERSONAS_PATH, BasePersona, load_personas


class TestPersonaLoading:
    def test_load_default_personas(self) -> None:
        personas = load_personas()
        assert len(personas) >= 12
        ids = [p.persona_id for p in personas]
        assert len(ids) == len(set(ids)), "persona_id 必须唯一"
        # 对抗画像存在（安全维依赖）
        assert "attacker" in ids

    def test_invalid_persona_fails_fast(self, tmp_path: Path) -> None:
        bad = [{
            "persona_id": "bad", "name": "x", "role": "r",
            "goal": "这是一个足够长的目标描述",
            "expected_tools": ["help_skill"],
            "success_criteria": ["帮助"],
            "tone": "ok", "prior_knowledge": [], "constraints": [],
        }]
        bad[0].pop("goal")  # 必填字段缺失
        path = tmp_path / "bad.yaml"
        path.write_text(yaml.safe_dump(bad), encoding="utf-8")
        with pytest.raises(ValueError):
            load_personas(path, validate_tools=False)

    def test_unknown_tool_rejected(self, tmp_path: Path) -> None:
        bad = [{
            "persona_id": "ghost_tool", "name": "x", "role": "r",
            "goal": "这是一个足够长的目标描述",
            "expected_tools": ["nonexistent_skill"],
            "success_criteria": ["帮助"],
        }]
        path = tmp_path / "bad.yaml"
        path.write_text(yaml.safe_dump(bad), encoding="utf-8")
        with pytest.raises(ValueError, match="manifest 不存在的技能"):
            load_personas(path)

    def test_adversarial_persona_allows_empty_lists(self) -> None:
        personas = load_personas()
        attacker = next(p for p in personas if p.persona_id == "attacker")
        assert attacker.is_adversarial is True
        assert attacker.expected_tools == []
        assert attacker.success_criteria == []
        assert isinstance(attacker, BasePersona)

    def test_default_file_exists(self) -> None:
        assert DEFAULT_PERSONAS_PATH.exists()
