"""集成测试5: RAG时间衰减 - 新旧矛盾文档排序验证"""
import os
import sys
import math
import pytest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.rag.hybrid_search import HybridSearcher, TIME_DECAY_LAMBDA


class TestRAGDecayFlow:
    """模拟: 两份矛盾文档(旧=佣金5%, 新=佣金8%), 验证新文档排前"""

    def setup_method(self):
        self.searcher = HybridSearcher.__new__(HybridSearcher)

    def test_new_doc_beats_old_doc(self):
        """新文档(2026-08-01)必须排在旧文档(2026-01-01)前面"""
        now = datetime.utcnow()
        old_date = now - timedelta(days=210)  # ~7个月前
        new_date = now - timedelta(days=2)    # 2天前

        results = [
            {
                "content": "平台佣金比例为5%(旧规则)",
                "score": 1.0,  # RRF 原始分相同
                "source": "vector",
                "last_updated": old_date.isoformat(),
            },
            {
                "content": "平台佣金比例为8%(新规则, 2026年8月生效)",
                "score": 1.0,  # RRF 原始分相同
                "source": "vector",
                "last_updated": new_date.isoformat(),
            },
        ]

        decayed = self.searcher._apply_time_decay(results)

        # 新文档必须排第一
        assert "8%" in decayed[0]["content"], \
            f"Expected new doc first, got: {decayed[0]['content']}"
        assert "5%" in decayed[1]["content"]

        # 新文档分数必须高于旧文档
        assert decayed[0]["score"] > decayed[1]["score"]

    def test_90_day_doc_40_percent_weight(self):
        """90天前的文档权重应约为原来的40%"""
        now = datetime.utcnow()
        results = [
            {
                "content": "old doc",
                "score": 1.0,
                "source": "vector",
                "last_updated": (now - timedelta(days=90)).isoformat(),
            },
        ]
        decayed = self.searcher._apply_time_decay(results)
        # exp(-0.01 * 90) = exp(-0.9) ≈ 0.406
        assert 0.35 < decayed[0]["score"] < 0.45

    def test_30_day_prompt_hint(self):
        """30天内的文档衰减很小(>70%)"""
        now = datetime.utcnow()
        results = [
            {
                "content": "recent doc",
                "score": 1.0,
                "source": "vector",
                "last_updated": (now - timedelta(days=30)).isoformat(),
            },
        ]
        decayed = self.searcher._apply_time_decay(results)
        assert decayed[0]["score"] > 0.70

    def test_no_timestamp_no_decay(self):
        """无 last_updated 字段的文档不衰减"""
        results = [
            {"content": "doc A", "score": 0.9, "source": "vector"},
            {"content": "doc B", "score": 0.8, "source": "bm25"},
        ]
        decayed = self.searcher._apply_time_decay(results)
        assert decayed[0]["score"] == 0.9
        assert decayed[1]["score"] == 0.8

    def test_mixed_with_and_without_timestamp(self):
        """有时间戳的衰减, 无时间戳的不变"""
        now = datetime.utcnow()
        results = [
            {
                "content": "old with ts",
                "score": 1.0,
                "source": "vector",
                "last_updated": (now - timedelta(days=180)).isoformat(),
            },
            {
                "content": "no ts",
                "score": 0.5,
                "source": "bm25",
            },
        ]
        decayed = self.searcher._apply_time_decay(results)
        # old with ts: 1.0 * exp(-0.01*180) = 1.0 * 0.165 = 0.165
        # no ts: 0.5 (unchanged)
        assert decayed[0]["content"] == "no ts"  # 0.5 > 0.165
        assert decayed[1]["content"] == "old with ts"

    def test_decay_lambda_configurable(self):
        """TIME_DECAY_LAMBDA 默认值为 0.01"""
        assert TIME_DECAY_LAMBDA == 0.01

    def test_search_method_integrates_decay(self):
        """search 方法中必须调用 _apply_time_decay"""
        import inspect
        source = inspect.getsource(HybridSearcher.search)
        assert "_apply_time_decay" in source
        # 必须在 rerank 之前
        decay_pos = source.index("self._apply_time_decay")
        rerank_pos = source.index("self._rerank(")
        assert decay_pos < rerank_pos, "time decay must run before rerank"