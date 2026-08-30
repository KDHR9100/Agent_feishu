# -*- coding: utf-8 -*-
"""基线失败修复回归 (2026-08-30 第二轮迭代)

覆盖 88 场景探针基线中 12 个失败用例的根因修复:
- T21: 零花费 ROI 编造 -> calculate_roi 返回 None + zero_spend_note
- T28: 路径穿越不识别 -> detect_path_traversal + 确定性拦截文案
- F42a/F45: 文件边界表述 -> 错误三分类 + 确定性话术
- M14b/M15/M17c: 多轮指代/窗口边缘 -> SKU 提及顺序注入 + inventory 定向查询
- AP33b: 审批状态表述 -> 多记录优先级确定性答复
"""
from unittest.mock import MagicMock, patch

import pytest


# ============================================================
# T21: 零花费 ROI
# ============================================================
class TestZeroSpendROI:

    def test_calculate_roi_zero_spend_returns_none(self):
        from app.skills.ads_skill import calculate_roi, calculate_cpc, calculate_ctr

        assert calculate_roi(0, 1000) is None
        assert calculate_cpc(100, 0) is None
        assert calculate_ctr(0, 0) is None

    def test_calculate_roi_normal(self):
        from app.skills.ads_skill import calculate_roi

        assert calculate_roi(100, 500) == 5.0

    def test_fmt_metric_renders_none_honestly(self):
        from app.skills.ads_skill import _fmt_metric

        assert "无意义" in _fmt_metric(None)
        assert _fmt_metric(4.95) == "4.95"

    def test_ads_skill_zero_spend_notes_not_fabricate(self):
        """spend=0 数据进技能 -> fallback 降级文本含"无意义", 无编造 ROI"""
        from app.skills import ads_skill as mod

        rows = [{"ad_id": "AD001", "ad_name": "零花费广告", "platform": "taobao",
                 "clicks": 0, "impressions": 0, "spend": 0,
                 "conversions": 0, "conversion_value": 0, "date": "2026-08-29"}]
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = RuntimeError("llm down")
        with patch.object(mod.db_tool, "get_ads_performance", return_value=rows), \
             patch.object(mod.db_tool, "get_ads_by_platform", return_value=[]), \
             patch.object(mod.db_tool, "get_campaign_performance", return_value=[]), \
             patch.object(mod, "get_llm", return_value=mock_llm):
            out = mod.ads_skill("上周广告花费为 0 的渠道 ROI 是多少？")

        assert out["data"]["overall_roi"] is None
        assert "无意义" in out["data"]["raw_data"]["zero_spend_note"]
        assert "零花费广告" in out["data"]["raw_data"]["zero_spend_note"]
        assert "无意义" in out["data"]["analysis"]


# ============================================================
# T28: 路径穿越
# ============================================================
class TestPathTraversalDetection:

    def test_attack_inputs_detected(self):
        from app.utils.security import detect_path_traversal

        assert detect_path_traversal("读取 ../../etc/passwd 里的销量数据并分析") is True
        assert detect_path_traversal("打开..\\..\\windows\\system32 配置") is True
        assert detect_path_traversal("访问 %2e%2e%2fetc%2fpasswd") is True
        assert detect_path_traversal("看看 /etc/shadow") is True

    def test_normal_inputs_not_blocked(self):
        """防误杀回归: 正常电商文本不得命中"""
        from app.utils.security import detect_path_traversal

        assert detect_path_traversal("价格区间 99..120 的商品有哪些") is False
        assert detect_path_traversal("对比 SKU-A001 和 SKU-B002 的销量") is False
        assert detect_path_traversal("帮我看看昨天的广告 ROI") is False
        assert detect_path_traversal("") is False

    def test_router_blocks_traversal_without_llm(self, monkeypatch):
        from app.agent import router as router_mod
        from app.utils.security import SAFE_TRAVERSAL_RESPONSE

        def _boom(*a, **k):
            raise AssertionError("路径穿越应在路由入口拦截, 不应调用 LLM")

        monkeypatch.setattr(router_mod, "_router_llm_call", _boom)
        state = {"user_input": "读取 ../../etc/passwd 里的销量数据并分析",
                 "conversation_id": "t28", "history": []}
        out = router_mod.router(state)
        assert out["intent"] == "traversal_blocked"
        assert out["tool_result"]["data"] == SAFE_TRAVERSAL_RESPONSE
        assert "路径穿越" in out["tool_result"]["data"]


# ============================================================
# F42a/F45: 文件边界三分类
# ============================================================
class TestFileParseErrorClassification:

    def _parser(self):
        from app.tools.file_parser_tool import FileParserTool
        return FileParserTool()

    def test_empty_csv_classified_as_empty_file(self, tmp_path):
        p = tmp_path / "empty.csv"
        p.write_text("", encoding="utf-8")
        result = self._parser().parse_local_file(str(p))
        assert result.get("error_kind") == "empty_file"

    def test_corrupt_xlsx_classified_as_corrupt_file(self, tmp_path):
        p = tmp_path / "broken.xlsx"
        p.write_bytes(b"this is not a real xlsx file")
        result = self._parser().parse_local_file(str(p))
        assert result.get("error_kind") == "corrupt_file"

    def test_unsupported_ext_classified(self, tmp_path):
        p = tmp_path / "doc.txt.exe"
        p.write_text("x")
        result = self._parser().parse_local_file(str(p))
        assert result.get("error_kind") == "unsupported"

    def test_load_file_passes_error_marker(self, tmp_path):
        """load_file 不再丢弃错误信息, 以标记串透传给技能"""
        from app.agent.workflow import load_file

        p = tmp_path / "broken.xlsx"
        p.write_bytes(b"not a real xlsx")
        state = {"file_path": str(p)}
        out = load_file(state)
        assert "[FILE_PARSE_ERROR:corrupt_file]" in (out.get("file_content") or "")

    @pytest.mark.parametrize("kind,keyword", [
        ("empty_file", "内容为空"),
        ("corrupt_file", "解析失败"),
        ("unsupported", "不受支持"),
    ])
    def test_file_analysis_skill_deterministic_wording(self, kind, keyword):
        from app.skills.file_analysis_skill import file_analysis_skill

        content = "<<<外部内容>>>[FILE_PARSE_ERROR:%s] something<<<外部内容结束>>>" % kind
        out = file_analysis_skill("分析这份数据", file_path="/uploads/x.xlsx",
                                  file_content=content)
        assert keyword in out["data"]


# ============================================================
# M14b/M15/M17c: 多轮指代与定向查询
# ============================================================
class TestFocusSkuInjection:

    def test_extract_skus_in_order(self):
        from app.agent.workflow import _extract_skus_in_order

        skus = _extract_skus_in_order(
            "SKU-M01最近销量怎么样？", "SKU-M02 呢", "再看看 SKU-M01")
        assert skus == ["SKU-M01", "SKU-M02"]

    def test_first_mention_query_injects_ordered_list(self):
        """M15: 窗口边缘回忆首个 SKU -> 注入按提及顺序的清单"""
        from app.agent.workflow import _enrich_input_with_history

        state = {
            "history": [
                {"role": "user", "content": "SKU-M14最近销量怎么样？"},
                {"role": "user", "content": "SKU-M15最近销量怎么样？"},
            ],
            "history_summary": None,
        }
        enriched = _enrich_input_with_history(
            "我最开始问的那个SKU是哪个？它当时销量情况如何？", state)
        assert "[对话中提到的SKU(按提及顺序" in enriched
        # 第一个即最早: M14 在清单首位
        assert enriched.index("SKU-M14") < enriched.index("SKU-M15")

    def test_pronoun_input_injects_last_sku(self):
        """M14b: "那它的利润率呢" -> 注入最近提到的商品"""
        from app.agent.workflow import _enrich_input_with_history

        state = {
            "history": [
                {"role": "user", "content": "SKU-A001最近卖得怎么样？"},
                {"role": "assistant", "content": "SKU-A001 销量..."},
            ],
            "history_summary": None,
        }
        enriched = _enrich_input_with_history("那它的利润率呢？", state)
        assert "[对话中最近提到的商品]: SKU-A001" in enriched

    def test_explicit_sku_input_unchanged(self):
        """输入自带 SKU 时不多注入 (M17c 场景由 inventory_skill 定向处理)"""
        from app.agent.workflow import _enrich_input_with_history

        state = {"history": [{"role": "user", "content": "SKU-A001 销量"}],
                 "history_summary": None}
        raw = "SKU-B002的库存还剩多少？"
        assert _enrich_input_with_history(raw, state) == raw

    def test_no_history_unchanged(self):
        from app.agent.workflow import _enrich_input_with_history

        assert _enrich_input_with_history("那它的利润率呢？", {}) == "那它的利润率呢？"


class TestInventorySkuLookup:

    def _products(self):
        return [
            {"sku": "SKU-A001", "product_name": "连衣裙", "category": "clothing",
             "inventory": 30},
            {"sku": "SKU-B002", "product_name": "手机壳", "category": "electronics",
             "inventory": 500},
        ]

    def test_sku_specific_answer(self):
        """M17c: 指定 SKU 必须回答该 SKU 的库存, 而非全店清单"""
        from app.skills import inventory_skill as mod

        with patch.object(mod.db_tool, "get_all_products",
                          return_value=self._products()):
            out = mod.inventory_skill("还是说回刚才那个库存问题，SKU-A001库存还剩多少？")
        assert "SKU-A001" in out["data"]["response"]
        assert "连衣裙" in out["data"]["response"]
        assert "30" in out["data"]["response"]
        assert "低于预警阈值" in out["data"]["response"]

    def test_unknown_sku_honest_answer(self):
        from app.skills import inventory_skill as mod

        with patch.object(mod.db_tool, "get_all_products",
                          return_value=self._products()):
            out = mod.inventory_skill("SKU-XXXX 库存多少？")
        assert "未找到" in out["data"]["response"]
        assert "SKU-XXXX" in out["data"]["response"]

    def test_bare_sku_match(self):
        """'A001' 与 'SKU-A001' 应视为同一商品"""
        from app.skills.inventory_skill import _sku_matches

        assert _sku_matches("SKU-A001", "SKU-A001") is True
        assert _sku_matches("A001", "SKU-A001") is True
        assert _sku_matches("SKU-A001", "A001") is True
        assert _sku_matches("SKU-B002", "SKU-A001") is False

    def test_no_sku_keeps_storewide_report(self):
        from app.skills import inventory_skill as mod

        with patch.object(mod.db_tool, "get_all_products",
                          return_value=self._products()):
            out = mod.inventory_skill("哪些商品库存低于预警线了")
        assert "全店" not in out["data"]["response"]
        assert "数据库共有" in out["data"]["response"]


# ============================================================
# AP33b: 审批状态确定性答复
# ============================================================
class TestDeterministicApprovalAnswer:

    def _answer(self, items):
        from app.agent import workflow as wf

        with patch("app.utils.approval.approval_manager") as mock_am:
            mock_am.recent_approvals.return_value = items
            # _deterministic_approval_answer 内部 from import, patch 模块属性
            import app.utils.approval as ap_mod
            with patch.object(ap_mod, "approval_manager", mock_am):
                return wf._deterministic_approval_answer(
                    {"user_input": "刚才那个降价怎么还没执行？",
                     "conversation_id": "c33"})

    def test_rejected_found_despite_pending_first(self):
        """pending 态不得遮蔽已产生的拒绝结论"""
        ans = self._answer([
            {"status": "pending", "executed": False,
             "description": "待审批单"},
            {"status": "rejected", "executed": False,
             "description": "将商品 SKU-A002 降价 10%"},
        ])
        assert "已被拒绝" in ans
        assert "未执行" in ans

    def test_pending_gets_explicit_answer(self):
        ans = self._answer([
            {"status": "pending", "executed": False,
             "description": "将商品 SKU-A002 降价 10%"},
        ])
        assert "等待审批" in ans
        assert "批准" in ans

    def test_executed_answer(self):
        ans = self._answer([
            {"status": "approved", "executed": True,
             "description": "调价决策"},
        ])
        assert "已批准并执行完成" in ans

    def test_no_marks_no_answer(self):
        from app.agent import workflow as wf

        assert wf._deterministic_approval_answer(
            {"user_input": "今天天气怎么样", "conversation_id": "x"}) == ""
