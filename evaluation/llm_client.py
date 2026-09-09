"""统一 LLM 客户端。

评测模块所有 LLM 调用（模拟用户 / 评测裁判）都经由此模块，支持：

- ``EVAL_SIM_*`` / ``EVAL_JUDGE_*`` 环境变量显式指定；
- 回退 ``OPENAI_BASE_URL`` / ``OPENAI_API_KEY``（可指向本地 vLLM）；
- ``EVAL_MODE=mock`` 时完全不实例化任何真实客户端（CI 零 token）。
"""

from __future__ import annotations

import re
from typing import Deque, List, Optional
from collections import deque

import structlog

from evaluation.config import EvalSettings

logger = structlog.get_logger(__name__)


class EvalConfigError(RuntimeError):
    """real 模式下 LLM 配置缺失。"""


def strip_thinking(text: str) -> str:
    """去掉推理型模型的 <think> 段落与首尾空白。"""

    if "</think>" in text:
        text = text.rsplit("</think>", 1)[-1]
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"<think>.*", "", text, flags=re.DOTALL)
    return text.strip()


class LLMClient:
    """LLM 客户端抽象：输入 prompt，输出纯文本回复。"""

    def invoke(self, prompt: str) -> str:  # pragma: no cover - 抽象
        raise NotImplementedError


class ScriptedLLMClient(LLMClient):
    """脚本化客户端（测试 / mock 用）：按序返回预置回复。"""

    def __init__(self, responses: Optional[List[str]] = None) -> None:
        self._responses: Deque[str] = deque(responses or [])
        self.prompts: List[str] = []

    def invoke(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self._responses:
            return "FINISHED"
        return self._responses.popleft()


class OpenAICompatLLMClient(LLMClient):
    """OpenAI 兼容客户端（DashScope / DeepSeek / vLLM 等均可）。

    langchain-openai 延迟导入：mock 模式不需要该依赖被加载。
    """

    def __init__(
        self,
        api_base: str,
        api_key: str,
        model: str,
        temperature: float = 0.0,
        timeout: int = 60,
    ) -> None:
        if not api_base or not api_key or not model:
            raise EvalConfigError(
                "real 模式需要完整的 LLM 配置: "
                "EVAL_SIM_API_BASE/EVAL_SIM_API_KEY/EVAL_SIM_MODEL 或 "
                "EVAL_JUDGE_API_BASE/EVAL_JUDGE_API_KEY/EVAL_JUDGE_MODEL, "
                "或设置 OPENAI_BASE_URL/OPENAI_API_KEY"
            )
        self._api_base = api_base
        self._api_key = api_key
        self._model = model
        self._temperature = temperature
        self._timeout = timeout
        self._llm = None  # 延迟构建

    def _get_llm(self):  # noqa: ANN202 - 返回类型随延迟导入
        if self._llm is None:
            from langchain_openai import ChatOpenAI  # 延迟导入

            self._llm = ChatOpenAI(
                base_url=self._api_base,
                api_key=self._api_key,
                model=self._model,
                temperature=self._temperature,
                timeout=self._timeout,
            )
        return self._llm

    def invoke(self, prompt: str) -> str:
        from langchain_core.messages import HumanMessage  # 延迟导入

        response = self._get_llm().invoke([HumanMessage(content=prompt)])
        raw = response.content if hasattr(response, "content") else str(response)
        return strip_thinking(raw)


def build_sim_client(settings: EvalSettings) -> Optional[LLMClient]:
    """构建模拟用户客户端；real 模式配置缺失时抛 EvalConfigError。"""

    if settings.eval_mode == "mock":
        return None
    client = OpenAICompatLLMClient(
        api_base=settings.resolved_sim_base(),
        api_key=settings.resolved_sim_key(),
        model=settings.sim_model,
        temperature=settings.sim_temperature,
    )
    logger.info("sim_llm_ready", model=settings.sim_model, base=settings.resolved_sim_base())
    return client


def build_judge_client(settings: EvalSettings) -> Optional[LLMClient]:
    """构建裁判客户端；real 模式配置缺失时抛 EvalConfigError。

    裁判应与被测模型异源：同源时打 warning（自我对拍失真风险），
    不阻断运行——报告里会保留该风险提示。
    """

    if settings.eval_mode == "mock":
        return None
    client = OpenAICompatLLMClient(
        api_base=settings.resolved_judge_base(),
        api_key=settings.resolved_judge_key(),
        model=settings.judge_model,
        temperature=settings.judge_temperature,
    )
    main_model = os_main_model()
    if main_model and settings.judge_model == main_model:
        logger.warning(
            "judge_same_source_as_target",
            judge_model=settings.judge_model,
            hint="裁判与被测模型同源, 存在自我对拍失真风险",
        )
    return client


def os_main_model() -> str:
    """读取被测 Agent 的主模型名（只读环境变量，不 import 主项目）。"""

    import os

    return os.getenv("LLM_MODEL_NAME", "")
