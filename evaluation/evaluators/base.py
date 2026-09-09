"""评测器基类与公共工具。

统一接口（任务书 M3）::

    class BaseEvaluator:
        name: str
        def evaluate(self, trajectory: dict, persona: BasePersona) -> EvalResult

EvalResult: {score: 0~1, passed: bool, reason: str, evidence: list[str]}
（附加 skipped 字段：该维对该 episode 不适用时置 True，聚合时剔除。）
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Optional

from pydantic import BaseModel, Field

from evaluation.config import EvalSettings
from evaluation.llm_client import LLMClient
from evaluation.personas.base_persona import BasePersona

#: 裁判 prompt 资产目录
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


class EvalResult(BaseModel):
    """单维度评测结果。"""

    score: float = Field(ge=0.0, le=1.0)
    passed: bool
    reason: str = ""
    evidence: list[str] = Field(default_factory=list)
    skipped: bool = False


class BaseEvaluator(ABC):
    """评测器抽象基类。"""

    name: str = "base"

    def __init__(
        self,
        settings: EvalSettings,
        judge: Optional[LLMClient] = None,
    ) -> None:
        self.settings = settings
        self.judge = judge

    @abstractmethod
    def evaluate(self, trajectory: dict, persona: BasePersona) -> EvalResult: ...

    def threshold(self) -> float:
        return float(self.settings.thresholds.get(self.name, 0.0))

    def _passed(self, score: float) -> bool:
        return score >= self.threshold()


def load_prompt(filename: str) -> str:
    """读取 prompts/ 目录下的裁判提示词（.md 文件，便于迭代）。"""

    path = PROMPTS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"裁判 prompt 缺失: {path}")
    return path.read_text(encoding="utf-8")


def parse_json_loose(text: str) -> Optional[Dict[str, object]]:
    """宽松解析裁判输出中的 JSON 对象（容忍 markdown 代码块包裹）。"""

    if not text:
        return None
    cleaned = re.sub(r"```(?:json)?", "", text)
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None
