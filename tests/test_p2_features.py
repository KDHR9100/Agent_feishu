"""P2 任务6/7/8: 流式响应+时间衰减+人工审批 单元测试"""
import os
import sys
import math
import time
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# 任务6: 飞书流式响应
# ============================================================
class TestStreamingWorkflow:

    def test_feishu_ws_uses_stream(self):
        import inspect
        with open("app/tools/feishu_ws.py", "r", encoding="utf-8") as f:
            source = f.read()
        assert "agent.stream" in source
        assert "progress_sent" in source

    def test_feishu_ws_has_fallback_invoke(self):
        with open("app/tools/feishu_ws.py", "r", encoding="utf-8") as f:
            source = f.read()
        assert "agent.invoke" in source  # fallback still exists

    def test_progress_messages_defined(self):
        with open("app/tools/feishu_ws.py", "r", encoding="utf-8") as f:
            source = f.read()
        assert "router" in source
        assert "skill_executor" in source


# ============================================================
# 任务7: RAG 时间衰减
# ============================================================
class TestTimeDecay:

    def test_time_decay_lambda_defined(self):
        from app.rag.hybrid_search import TIME_DECAY_LAMBDA
        assert TIME_DECAY_LAMBDA == 0.01

    def test_apply_time_decay_method_exists(self):
        from app.rag.hybrid_search import HybridSearcher
        assert hasattr(HybridSearcher, "_apply_time_decay")

    def test_decay_formula_90_days(self):
        from app.rag.hybrid_search import TIME_DECAY_LAMBDA
        # 90天前的文档权重应约为 exp(-0.01*90) = exp(-0.9) ≈ 0.406
        decay_90 = math.exp(-TIME_DECAY_LAMBDA * 90)
        assert 0.35 < decay_90 < 0.45

    def test_decay_formula_30_days(self):
        from app.rag.hybrid_search import TIME_DECAY_LAMBDA
        decay_30 = math.exp(-TIME_DECAY_LAMBDA * 30)
        assert 0.70 < decay_30 < 0.78

    def test_apply_time_decay_with_metadata(self):
        from app.rag.hybrid_search import HybridSearcher
        searcher = HybridSearcher.__new__(HybridSearcher)
        now = datetime.utcnow()
        results = [
            {"content": "new doc", "score": 1.0, "source": "vector",
             "last_updated": now.isoformat()},
            {"content": "old doc", "score": 1.0, "source": "vector",
             "last_updated": (now - timedelta(days=90)).isoformat()},
        ]
        decayed = searcher._apply_time_decay(results)
        # 新文档分数应高于旧文档
        assert decayed[0]["content"] == "new doc"
        assert decayed[0]["score"] > decayed[1]["score"]

    def test_apply_time_decay_no_metadata(self):
        from app.rag.hybrid_search import HybridSearcher
        searcher = HybridSearcher.__new__(HybridSearcher)
        results = [
            {"content": "doc A", "score": 0.8, "source": "vector"},
            {"content": "doc B", "score": 0.6, "source": "bm25"},
        ]
        decayed = searcher._apply_time_decay(results)
        # 无时间元数据时分数不变
        assert decayed[0]["score"] == 0.8
        assert decayed[1]["score"] == 0.6

    def test_search_method_calls_time_decay(self):
        import inspect
        from app.rag.hybrid_search import HybridSearcher
        source = inspect.getsource(HybridSearcher.search)
        assert "_apply_time_decay" in source


# ============================================================
# 任务8: 人工审批
# ============================================================
class TestApprovalManager:

    def test_create_approval(self):
        from app.utils.approval import ApprovalManager
        mgr = ApprovalManager()
        aid = mgr.create_approval(
            action_name="modify_inventory",
            action_func=lambda: "done",
            description="修改库存",
        )
        assert aid is not None
        assert mgr.pending_count == 1

    def test_approve_executes_action(self):
        from app.utils.approval import ApprovalManager
        mgr = ApprovalManager()
        result_holder = []
        aid = mgr.create_approval(
            action_name="test_action",
            action_func=lambda x: result_holder.append(x),
            action_args=("hello",),
        )
        mgr.approve(aid)
        assert result_holder == ["hello"]
        assert mgr.pending_count == 0

    def test_reject_removes_entry(self):
        from app.utils.approval import ApprovalManager
        mgr = ApprovalManager()
        aid = mgr.create_approval("act", lambda: None)
        assert mgr.reject(aid) is True
        assert mgr.pending_count == 0

    def test_reject_nonexistent(self):
        from app.utils.approval import ApprovalManager
        mgr = ApprovalManager()
        assert mgr.reject("nonexistent") is False

    def test_expired_approval(self):
        from app.utils.approval import ApprovalManager, APPROVAL_TIMEOUT
        mgr = ApprovalManager()
        aid = mgr.create_approval("act", lambda: "should_not_run")
        # 手动设置为过期
        mgr._pending[aid]["created_at"] = time.time() - APPROVAL_TIMEOUT - 1
        result = mgr.approve(aid)
        assert result is None

    def test_get_pending(self):
        from app.utils.approval import ApprovalManager
        mgr = ApprovalManager()
        aid = mgr.create_approval("act", lambda: None, description="test desc")
        entry = mgr.get_pending(aid)
        assert entry is not None
        assert entry["description"] == "test desc"
        assert entry["status"] == "pending"

    def test_cleanup_expired(self):
        from app.utils.approval import ApprovalManager, APPROVAL_TIMEOUT
        mgr = ApprovalManager()
        aid1 = mgr.create_approval("act1", lambda: None)
        aid2 = mgr.create_approval("act2", lambda: None)
        mgr._pending[aid1]["created_at"] = time.time() - APPROVAL_TIMEOUT - 10
        mgr.cleanup_expired()
        assert mgr.pending_count == 1  # only aid2 remains

    def test_requires_approval_skills_defined(self):
        from app.utils.approval import REQUIRES_APPROVAL_SKILLS
        assert "inventory_skill" in REQUIRES_APPROVAL_SKILLS
        assert "support_skill" in REQUIRES_APPROVAL_SKILLS

    def test_skill_markers(self):
        import app.skills.inventory_skill as inv
        import app.skills.support_skill as sup
        assert getattr(inv, "requires_approval", False) is True
        assert getattr(sup, "requires_approval", False) is True