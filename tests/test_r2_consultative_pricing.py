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
