"""Persona 数据模型（Pydantic 校验，YAML 加载即失败快报）。"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ConsistencyProbe(BaseModel):
    """多轮一致性探针：第 at_turn 轮的回答必须记得 expect_reference。"""

    model_config = ConfigDict(extra="forbid")

    at_turn: int = Field(ge=1, description="探针所在轮次（1 起）")
    expect_reference: str = Field(min_length=1, description="该轮回答必须包含的实体引用")
    description: str = ""


class BasePersona(BaseModel):
    """合成用户画像。

    字段至少覆盖任务书要求：persona_id/name/role/goal/tone/prior_knowledge/
    constraints/expected_tools/success_criteria；附加 mock 话术与探针字段。
    """

    model_config = ConfigDict(extra="forbid")

    persona_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1)
    role: str = Field(min_length=1)
    goal: str = Field(min_length=8, description="具体到可判断的目标")
    tone: str = ""
    prior_knowledge: List[str] = Field(default_factory=list)
    constraints: List[str] = Field(
        default_factory=list,
        description="行为约束，如: 20% 概率打错字 / 一次提多个需求 / 会跑题",
    )
    expected_tools: List[str] = Field(default_factory=list)
    success_criteria: List[str] = Field(default_factory=list)

    # ---- 评测辅助字段 ----
    script: List[str] = Field(default_factory=list, description="mock 模式预置话术")
    consistency_probes: List[ConsistencyProbe] = Field(default_factory=list)
    is_adversarial: bool = False
    max_turns_override: Optional[int] = Field(default=None, ge=1, le=20)

    @model_validator(mode="after")
    def _validate_required_lists(self) -> "BasePersona":
        """常规画像必须声明 expected_tools/success_criteria；对抗画像允许为空。"""

        if not self.is_adversarial:
            if not self.expected_tools:
                raise ValueError("非对抗画像必须声明 expected_tools")
            if not self.success_criteria:
                raise ValueError("非对抗画像必须声明 success_criteria")
        return self
