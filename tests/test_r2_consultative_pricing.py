# -*- coding: utf-8 -*-
"""R2 回归: 竞品降价跟进的咨询类问题只分析、不误触发调价审批"""
import re

from app.skills.pricing_skill import pricing_skill, _parse_target_price


class TestConsultativePricing:
    def test_consultative_question_not_executable(self):
        result = pricing_skill("竞品把同款降到39元了，我要不要跟进降价？我们当前售价49元")
        assert result["is_executable"] is False
        assert result["execution_request"] is None
        text = result["data"]["analysis"]
        assert "咨询模式" in text
        assert "审批卡片" not in text
        assert len(text) >= 100

    def test_consultative_marks_variants(self):
        for msg in ("该不该跟着降价", "需不需要跟进降价", "跟不跟这个价"):
            r = pricing_skill(msg)
            assert r["is_executable"] is False, msg
            assert r["execution_request"] is None, msg

    def test_competitor_price_not_parsed_as_target(self):
        # 竞品分句里的 "降到39元" 不应成为目标价; 用户自己的 "降到45元" 才是
        assert _parse_target_price("竞品把同款降到39元了，把我们价格降到45元") == 45.0
        # 纯竞品描述: 无目标价
        assert _parse_target_price("竞品把同款降到39元了，我们当前售价49元") is None

    def test_directive_still_executable(self):
        result = pricing_skill("把SKU-A001降价到99元，当前售价120元")
        assert result["is_executable"] is True
        req = result["execution_request"]
        assert req["action"] == "update_price"
        assert req["params"]["new_price"] == 99.0

    def test_plain_target_price_unaffected(self):
        assert _parse_target_price("帮我把爆款价格降到 101") == 101.0
        assert _parse_target_price("涨 10%，最终调到 115") == 115.0

    def test_advice_question_not_executable(self):
        """问价式咨询('卖多少钱合适'): 只给建议, 绝不触发改价执行"""
        for msg in ("这个商品卖多少钱合适", "定价建议？", "帮我定个价", "该定多少钱"):
            r = pricing_skill(msg)
            assert r["is_executable"] is False, msg
            assert r["execution_request"] is None, msg
            assert "未发起任何调价操作" in r["data"]["analysis"], msg

    def test_has_explicit_directive_gate(self):
        """问价咨询与调价指令的门控判定: 只有明示指令才算可执行"""
        from app.skills.pricing_skill import has_explicit_directive
        # 明示调价指令 → True(后续走审批链路)
        assert has_explicit_directive("降价 20%") is True
        assert has_explicit_directive("调价到 79.2") is True
        assert has_explicit_directive("帮我把爆款价格降到 101") is True
        # 咨询问句 → False(绝不执行)
        assert has_explicit_directive("卖多少钱合适") is False
        assert has_explicit_directive("帮我定价") is False
        assert has_explicit_directive("我要不要跟进降价") is False
