# -*- coding: utf-8 -*-
"""ads_skill 健壮性测试: DB 聚合字段为 None 时不得崩溃"""
from app.skills.ads_skill import compare_platforms


class TestComparePlatformsRobust:
    def test_none_values_no_crash(self):
        data = [
            {"platform": "taobao", "avg_roas": None, "avg_cpc": None, "avg_ctr": None},
            {"platform": "douyin", "avg_roas": 2.5, "avg_cpc": 1.2, "avg_ctr": 3.4},
        ]
        result = compare_platforms(data)
        assert result["best_roas_platform"] == "douyin"
        assert result["lowest_cpc_platform"] == "douyin"
        assert result["highest_ctr_platform"] == "douyin"

    def test_invalid_input_no_crash(self):
        assert compare_platforms(None)["best_roas"] is None
        assert compare_platforms({"error": "x"})["best_roas"] is None
        assert compare_platforms(["not-a-dict"])["best_roas"] is None

    def test_missing_keys_no_crash(self):
        result = compare_platforms([{"platform": "xhs"}])
        assert result["best_roas"] == 0
        assert result["best_roas_platform"] == "xhs"
