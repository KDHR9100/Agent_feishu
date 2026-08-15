# -*- coding: utf-8 -*-
"""
代码质量修复验证测试

覆盖以下修复项:
- P0-1: config.py LLM 全局实例线程安全 (double-checked locking)
- P0-2: config.py get_embeddings() 死代码消除 + ImportError 降级
- P0-3: hybrid_search.py Rerank 模型不再重复加载
- P1-4: prompts.py 不再包含重复的 PLANNER_PROMPT
- P1-5: /health 和 /health/details 端点保持向后兼容
- P1-6: vectorstore timeout 使用共享线程池
- P2-7: main.py 无注释掉的 Webhook 死代码
"""

import threading
import unittest
from unittest.mock import patch, MagicMock


# ============================================================
# P0-1: LLM 实例线程安全
# ============================================================
class TestLLMThreadSafety(unittest.TestCase):
    """验证 LLM 全局实例的 double-checked locking 线程安全"""

    def setUp(self):
        """每个测试前重置全局状态"""
        import app.config as cfg
        cfg._llm_instance = None
        cfg._router_llm_instance = None
        cfg._fallback_llm_instance = None

    def test_lock_exists(self):
        """_llm_lock 应该是一个 threading.Lock 实例"""
        from app.config import _llm_lock
        self.assertIsInstance(_llm_lock, type(threading.Lock()))

    @patch("app.config.config")
    def test_get_llm_double_check(self, mock_config):
        """并发调用 get_llm 只应创建一个实例"""
        import app.config as cfg

        mock_llm = MagicMock()
        call_count = [0]

        def fake_chat_openai(**kwargs):
            call_count[0] += 1
            return mock_llm

        with patch("langchain_openai.ChatOpenAI", side_effect=fake_chat_openai):
            with patch("app.utils.token_tracker.TokenTrackingHandler"):
                results = []
                errors = []

                def worker():
                    try:
                        result = cfg.get_llm()
                        results.append(result)
                    except Exception as e:
                        errors.append(e)

                threads = [threading.Thread(target=worker) for _ in range(5)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join(timeout=10)

        self.assertEqual(len(errors), 0, "Threads should not raise errors: %s" % errors)
        # 所有线程应返回同一实例
        self.assertTrue(all(r is results[0] for r in results))
        # ChatOpenAI 只应被调用一次（double-check 生效）
        self.assertEqual(call_count[0], 1)

    @patch("app.config.config")
    def test_get_router_llm_double_check(self, mock_config):
        """并发调用 get_router_llm 只应创建一个实例"""
        import app.config as cfg

        mock_llm = MagicMock()
        call_count = [0]

        def fake_chat_openai(**kwargs):
            call_count[0] += 1
            return mock_llm

        with patch("langchain_openai.ChatOpenAI", side_effect=fake_chat_openai):
            with patch("app.utils.token_tracker.TokenTrackingHandler"):
                results = []

                def worker():
                    results.append(cfg.get_router_llm())

                threads = [threading.Thread(target=worker) for _ in range(5)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join(timeout=10)

        self.assertTrue(all(r is results[0] for r in results))
        self.assertEqual(call_count[0], 1)

    def test_get_fallback_llm_no_model_returns_none(self):
        """未配置 LLM_FALLBACK_MODEL 时 get_fallback_llm 返回 None"""
        import app.config as cfg
        with patch.object(cfg.config, "LLM_FALLBACK_MODEL", ""):
            result = cfg.get_fallback_llm()
            self.assertIsNone(result)


# ============================================================
# P0-2: get_embeddings() 死代码消除 + 降级
# ============================================================
class TestGetEmbeddingsFix(unittest.TestCase):
    """验证 get_embeddings 无死代码，ImportError 时降级到远程"""

    def setUp(self):
        import app.config as cfg
        self._orig_use_local = cfg.config.USE_LOCAL_EMBEDDING

    def tearDown(self):
        import app.config as cfg
        cfg.config.USE_LOCAL_EMBEDDING = self._orig_use_local

    def test_local_embedding_success(self):
        """本地 Embedding 正常初始化"""
        import app.config as cfg
        cfg.config.USE_LOCAL_EMBEDDING = True

        mock_embeddings = MagicMock()
        with patch("langchain_huggingface.HuggingFaceEmbeddings", return_value=mock_embeddings):
            result = cfg.get_embeddings()
            self.assertIs(result, mock_embeddings)

    def test_local_import_error_fallback_to_remote(self):
        """本地 ImportError 时降级到远程 Embedding"""
        import app.config as cfg
        cfg.config.USE_LOCAL_EMBEDDING = True

        mock_remote = MagicMock()
        with patch("langchain_huggingface.HuggingFaceEmbeddings", side_effect=ImportError("no module")):
            with patch("langchain_openai.OpenAIEmbeddings", return_value=mock_remote):
                result = cfg.get_embeddings()
                self.assertIs(result, mock_remote)

    def test_remote_embedding_when_local_disabled(self):
        """USE_LOCAL_EMBEDDING=false 时直接使用远程"""
        import app.config as cfg
        cfg.config.USE_LOCAL_EMBEDDING = False

        mock_remote = MagicMock()
        with patch("langchain_openai.OpenAIEmbeddings", return_value=mock_remote):
            result = cfg.get_embeddings()
            self.assertIs(result, mock_remote)


# ============================================================
# P0-3: Rerank 模型不再重复加载
# ============================================================
class TestRerankModelNoDoubleLoad(unittest.TestCase):
    """验证 HybridSearcher._load_rerank_model 只调用一次 CrossEncoder"""

    @patch("app.rag.hybrid_search._find_cached_model_path")
    def test_rerank_model_loaded_once(self, mock_find):
        """CrossEncoder 只应被实例化一次"""
        mock_find.return_value = "/fake/model/path"

        mock_cross_encoder = MagicMock()
        with patch("sentence_transformers.CrossEncoder", return_value=mock_cross_encoder) as mock_ce:
            from app.rag.hybrid_search import HybridSearcher
            searcher = HybridSearcher.__new__(HybridSearcher)
            searcher.vector_store = MagicMock()
            searcher.bm25 = None
            searcher.bm25_documents = []
            searcher.rerank_model = None
            searcher._rerank_available = False
            searcher._load_rerank_model()

            # CrossEncoder 只应被调用一次（修复前会调用两次）
            self.assertEqual(mock_ce.call_count, 1)
            self.assertTrue(searcher._rerank_available)
            self.assertIs(searcher.rerank_model, mock_cross_encoder)

    @patch("app.rag.hybrid_search._find_cached_model_path")
    def test_rerank_model_missing_no_crash(self, mock_find):
        """模型缓存不存在时优雅降级"""
        mock_find.return_value = None

        from app.rag.hybrid_search import HybridSearcher
        searcher = HybridSearcher.__new__(HybridSearcher)
        searcher.vector_store = MagicMock()
        searcher.bm25 = None
        searcher.bm25_documents = []
        searcher.rerank_model = None
        searcher._rerank_available = False
        searcher._load_rerank_model()

        self.assertFalse(searcher._rerank_available)
        self.assertIsNone(searcher.rerank_model)


# ============================================================
# P1-4: Planner Prompt 去重
# ============================================================
class TestPlannerPromptDedup(unittest.TestCase):
    """验证 prompts.py 不再包含重复的 PLANNER_PROMPT"""

    def test_no_planner_prompt_in_prompts_py(self):
        """prompts.py 中不应有 PLANNER_PROMPT 属性"""
        import app.prompts as prompts
        self.assertFalse(
            hasattr(prompts, "PLANNER_PROMPT"),
            "PLANNER_PROMPT should be removed from prompts.py (use workflow.py PLANNER_PROMPT_TEMPLATE)"
        )

    def test_planner_prompt_template_still_in_workflow(self):
        """workflow.py 中的 PLANNER_PROMPT_TEMPLATE 应仍然存在"""
        from app.agent.workflow import PLANNER_PROMPT_TEMPLATE
        self.assertIn("任务规划专家", PLANNER_PROMPT_TEMPLATE)
        self.assertIn("prev_output", PLANNER_PROMPT_TEMPLATE)


# ============================================================
# P1-5: /health 端点向后兼容
# ============================================================
class TestHealthEndpoints(unittest.TestCase):
    """验证 /health 和 /health/details 端点均正常工作"""

    def test_both_endpoints_registered(self):
        """两个端点都应注册在 FastAPI app 中"""
        from app.main import app
        routes = [getattr(r, "path", None) for r in app.routes if hasattr(r, "path")]
        self.assertIn("/health", routes)
        self.assertIn("/health/details", routes)


# ============================================================
# P1-6: vectorstore timeout 使用共享线程池
# ============================================================
class TestVectorstoreTimeoutSharedPool(unittest.TestCase):
    """验证 vectorstore.py 的 timeout 使用共享线程池"""

    def test_shared_executor_exists(self):
        """_VS_EXECUTOR 应存在且为 ThreadPoolExecutor"""
        from app.rag.vectorstore import _VS_EXECUTOR
        from concurrent.futures import ThreadPoolExecutor
        self.assertIsInstance(_VS_EXECUTOR, ThreadPoolExecutor)

    def test_timeout_uses_shared_pool(self):
        """timeout 装饰器应使用共享池而非每次创建"""
        import inspect
        from app.rag import vectorstore
        source = inspect.getsource(vectorstore.timeout)
        # 不应包含 'with ThreadPoolExecutor' (旧的逐次创建模式)
        self.assertNotIn("with ThreadPoolExecutor", source)
        # 应引用共享池
        self.assertIn("_VS_EXECUTOR", source)


# ============================================================
# P2-7: main.py 无 Webhook 死代码
# ============================================================
class TestMainDeadCodeCleanup(unittest.TestCase):
    """验证 main.py 已清理注释掉的 Webhook 路由"""

    def test_no_commented_webhook_code(self):
        """main.py 源码中不应包含注释掉的 feishu_router 代码"""
        import inspect
        from app import main
        source = inspect.getsource(main)
        self.assertNotIn("feishu_router", source)


if __name__ == "__main__":
    unittest.main()
