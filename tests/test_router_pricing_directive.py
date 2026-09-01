# -*- coding: utf-8 -*-
"""T34b 修复验证: 定价指令确定性快路径

动机: 路由模型较弱时 "SKU-A001改价到99" 曾被路由到 product_skill 输出无关报告,
调价审批门被整条绕过 —— 安全关键路径的路由不能依赖 LLM 能力。

设计约束(区别于裸关键词快路): 判别复用 pricing_skill.has_explicit_directive
的结构化指令解析(目标价/涨跌幅/折扣), 内置咨询句式/竞品语境/批量措辞剔除,
仅含价格词的歧义输入不得触发快路。
"""
from app.agent import router as router_mod


# ---------- 命中: 明示调价指令 ----------
def test_directive_inputs_hit_fast_path():
    f = router_mod._pricing_directive_hits
    assert f("SKU-A001改价到99", {}) is True              # T34b 原始失败用例
    assert f("把SKU-A001的价格改到 89.9", {}) is True
    assert f("帮我把爆款价格降到 79.2 元", {}) is True
    assert f("降价 20%", {}) is True
    assert f("打个八八折", {}) is True
    assert f("价格上调 15%", {}) is True


# ---------- 不命中: 歧义场景(用户明确要求的防误触发) ----------
def test_ambiguous_inputs_do_not_hit_fast_path():
    f = router_mod._pricing_directive_hits
    # 咨询句式: 征询建议而非下达指令
    assert f("竞品把价格杀到99了，我们要不要跟价", {}) is False
    assert f("要不要降价20%", {}) is False
    # 竞品语境: 描述市场, 不是自己的调价指令
    assert f("竞品降价了4%，我们销量会受影响吗", {}) is False
    # 创作素材语境: "降价"只是文案题材
    assert f("写一段降价20%的促销文案", {}) is False
    assert f("帮我写个打八八折的标题", {}) is False


# ---------- 不命中: 多意图守卫 ----------
def test_multi_intent_with_other_skill_confidence_does_not_hit():
    f = router_mod._pricing_directive_hits
    # 其余技能关键词 conf>=2 视为复合指令, 交回 LLM/规划器编排
    assert f("库存预警！然后把SKU001改价到99", {"inventory_skill": 2}) is False
    # 其余技能仅 conf=1(如 'SKU' 字样命中 product)不拦截快路径
    assert f("SKU001改价到99", {"product_skill": 1}) is True


# ---------- 开关: 可通过环境变量语义关闭 ----------
def test_fast_path_disabled_by_flag(monkeypatch):
    monkeypatch.setattr(router_mod, "PRICING_DIRECTIVE_FAST_PATH", False)
    assert router_mod._pricing_directive_hits("SKU-A001改价到99", {}) is False


# ---------- 端到端: 指令路由不经 LLM, 审批门不会被弱模型绕过 ----------
def test_router_routes_t34b_directive_without_llm(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("明示调价指令必须走确定性快路径, 不应调用路由 LLM")

    monkeypatch.setattr(router_mod, "_router_llm_call", _boom)
    state = {
        "user_input": "SKU-A001改价到99",
        "conversation_id": "t34b",
        "history": [],
    }
    out = router_mod.router(state)
    assert out["skills_to_execute"] == ["pricing_skill"]
    assert out["intent"] == "pricing_skill"


# ---------- 端到端: 歧义输入不走快路径, 仍由 LLM/关键词兜底裁决 ----------
def test_router_ambiguous_competitor_input_falls_through(monkeypatch):
    def _llm_down(*args, **kwargs):
        raise RuntimeError("llm down (test stub)")

    monkeypatch.setattr(router_mod, "_router_llm_call", _llm_down)
    state = {
        "user_input": "竞品把价格杀到99了，我们要不要跟价",
        "conversation_id": "t34b-b",
        "history": [],
    }
    out = router_mod.router(state)
    # LLM 失败后由关键词兜底: 竞品 -> competitor_skill, 绝非定价快路径
    assert out["intent"] == "competitor_skill"
