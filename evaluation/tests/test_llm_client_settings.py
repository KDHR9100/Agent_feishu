"""EvalSettings 超时/思考开关配置测试（裁判默认放宽的回归保护）。"""

from evaluation.config import EvalSettings
from evaluation.llm_client import OpenAICompatLLMClient


class TestTimeoutSettings:
    def test_default_timeouts(self):
        settings = EvalSettings(eval_mode="mock")
        assert settings.sim_timeout == 60
        # 裁判 prompt 含完整轨迹 + 评分细则，推理型模型 60s 实测会超时回退规则通道
        assert settings.judge_timeout == 240

    def test_timeout_env_override(self, monkeypatch):
        monkeypatch.setenv("EVAL_JUDGE_TIMEOUT", "300")
        monkeypatch.setenv("EVAL_SIM_TIMEOUT", "90")
        settings = EvalSettings(eval_mode="mock")
        assert settings.judge_timeout == 300
        assert settings.sim_timeout == 90


class TestDisableThinking:
    def test_default_off(self):
        # 默认关闭：OpenAI 等严格校验未知参数的 endpoint 不能收到 enable_thinking
        settings = EvalSettings(eval_mode="mock", _env_file=None)
        assert settings.judge_disable_thinking is False

    def test_extra_body_only_when_enabled(self, monkeypatch):
        monkeypatch.setenv("EVAL_JUDGE_DISABLE_THINKING", "true")
        settings = EvalSettings(eval_mode="mock", _env_file=None)
        on = OpenAICompatLLMClient(
            api_base="https://x", api_key="k", model="m",
            extra_body={"enable_thinking": False} if settings.judge_disable_thinking else None,
        )
        off = OpenAICompatLLMClient(api_base="https://x", api_key="k", model="m")
        assert on._extra_body == {"enable_thinking": False}
        assert off._extra_body is None
