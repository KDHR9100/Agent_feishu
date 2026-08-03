# -*- coding: utf-8 -*-
"""
混合搜索模块：BM25 关键词搜索 + FAISS 向量语义搜索 + 本地 Rerank 模型。

使用 Reciprocal Rank Fusion (RRF) 融合两路检索结果，
并通过 BAAI/bge-reranker-base 交叉编码器进行精排。
"""

import os
import time
import math
from datetime import datetime

from app.config import logger

# 混合搜索配置
HYBRID_ALPHA = float(os.getenv("HYBRID_ALPHA", "0.6"))  # 向量搜索权重 (0.6 偏向向量)
RERANK_TOP_K = int(os.getenv("RERANK_TOP_K", "5"))  # 最终输出数量
RERANK_MODEL_NAME = os.getenv("RERANK_MODEL_NAME", "BAAI/bge-reranker-base")
TIME_DECAY_LAMBDA = float(os.getenv("TIME_DECAY_LAMBDA", "0.01"))  # 时间衰减系数


def _find_cached_model_path(model_name):
    """从 HuggingFace 本地缓存中查找模型路径。"""
    cache_dir = os.path.expanduser("~/.cache/huggingface/hub")
    folder = "models--" + model_name.replace("/", "--")
    path = os.path.join(cache_dir, folder)
    if not os.path.exists(path):
        return None
    snapshots = os.path.join(path, "snapshots")
    if not os.path.exists(snapshots):
        return None
    dirs = os.listdir(snapshots)
    if dirs:
        return os.path.join(snapshots, dirs[0])
    return None


class HybridSearcher:
    """
    混合搜索器：结合 BM25 关键词检索和 FAISS 向量语义检索。

    工作流程:
    1. BM25 基于 jieba 分词进行关键词匹配
    2. FAISS 向量搜索进行语义匹配
    3. RRF 融合两路结果
    4. CrossEncoder 精排（可选）
    """

    def __init__(self, vector_store):
        """
        初始化混合搜索器。

        Args:
            vector_store: 现有的 VectorStore 实例 (app.rag.vectorstore.vector_store)
        """
        self.vector_store = vector_store
        self.bm25 = None
        self.bm25_documents = []  # 原始文档文本列表
        self.rerank_model = None
        self._rerank_available = False

        # 尝试加载 rerank 模型
        self._load_rerank_model()

    def _load_rerank_model(self):
        """加载本地 rerank 模型，失败时优雅降级。"""
        try:
            from sentence_transformers import CrossEncoder

            # 仅从本地缓存加载（离线环境不尝试在线下载）
            model_path = _find_cached_model_path(RERANK_MODEL_NAME)
            if model_path:
                logger.info("[HybridSearch] 从本地缓存加载 rerank 模型: %s", model_path)
                self.rerank_model = CrossEncoder(model_path, device="cpu")
            else:
                logger.warning("[HybridSearch] 本地缓存未找到 rerank 模型，跳过精排（离线模式）")
                self._rerank_available = False
                return

            self.rerank_model = CrossEncoder(model_path, device="cpu")
            self._rerank_available = True
            logger.info("[HybridSearch] Rerank 模型加载成功")
        except Exception as e:
            logger.warning("[HybridSearch] Rerank 模型加载失败，将跳过精排: %s", e)
            self._rerank_available = False

    def build_bm25_index(self, documents: list):
        """
        构建 BM25 索引。

        Args:
            documents: 文档文本列表（与 FAISS 中的 chunks 对应）
        """
        try:
            import jieba
            from rank_bm25 import BM25Okapi

            self.bm25_documents = documents

            # 使用 jieba 进行中文分词
            tokenized_docs = [jieba.lcut(doc) for doc in documents]
            self.bm25 = BM25Okapi(tokenized_docs)
            logger.info("[HybridSearch] BM25 索引构建完成，共 %d 个文档", len(documents))
        except ImportError as e:
            logger.warning("[HybridSearch] BM25 依赖缺失，关键词搜索不可用: %s", e)
            self.bm25 = None
        except Exception as e:
            logger.error("[HybridSearch] BM25 索引构建失败: %s", e)
            self.bm25 = None

    def search(self, query: str, k: int = 5, use_rerank: bool = True) -> list:
        """
        执行混合搜索。

        Args:
            query: 查询文本
            k: 返回结果数量
            use_rerank: 是否使用 rerank 精排

        Returns:
            [{"content": str, "score": float, "source": str}]
        """
        start_time = time.time()

        # 获取向量搜索结果
        vector_results = self._vector_search(query, k=k * 3)

        # 获取 BM25 搜索结果
        bm25_results = self._bm25_search(query, k=k * 3)

        # 如果 BM25 不可用，直接返回向量搜索结果
        if not bm25_results:
            logger.info("[HybridSearch] BM25 不可用，使用纯向量搜索")
            results = vector_results[:k]
        else:
            # RRF 融合
            results = self._rrf_merge(bm25_results, vector_results)

        # 时间衰减
        results = self._apply_time_decay(results)

        # Rerank 精排
        if use_rerank and self._rerank_available and results:
            rerank_start = time.time()
            results = self._rerank(query, results, top_k=k)
            rerank_time = time.time() - rerank_start
            logger.info("[HybridSearch] Rerank 耗时: %.3fs, 候选数: %d", rerank_time, len(results))
        else:
            results = results[:k]

        total_time = time.time() - start_time
        logger.info(
            "[HybridSearch] 搜索完成: 耗时=%.3fs, 结果数=%d, rerank=%s",
            total_time, len(results), "是" if (use_rerank and self._rerank_available) else "否"
        )

        return results

    def _vector_search(self, query: str, k: int = 10) -> list:
        """执行向量语义搜索。"""
        try:
            docs = self.vector_store.similarity_search(query, k=k)
            results = []
            for i, doc in enumerate(docs):
                results.append({
                    "content": doc.page_content,
                    "score": 1.0 / (i + 1),  # 按排名赋初始分数
                    "source": doc.metadata.get("source", "vector") if doc.metadata else "vector",
                })
            return results
        except Exception as e:
            logger.warning("[HybridSearch] 向量搜索失败: %s", e)
            return []

    def _bm25_search(self, query: str, k: int = 10) -> list:
        """执行 BM25 关键词搜索。"""
        if self.bm25 is None or not self.bm25_documents:
            return []

        try:
            import jieba

            tokenized_query = jieba.lcut(query)
            scores = self.bm25.get_scores(tokenized_query)

            # 获取 top-k 索引
            top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]

            results = []
            for idx in top_indices:
                if scores[idx] > 0:
                    results.append({
                        "content": self.bm25_documents[idx],
                        "score": float(scores[idx]),
                        "source": "bm25",
                    })
            return results
        except Exception as e:
            logger.warning("[HybridSearch] BM25 搜索失败: %s", e)
            return []

    def _rrf_merge(self, bm25_results: list, vector_results: list, k: int = 60) -> list:
        """
        使用 Reciprocal Rank Fusion (RRF) 融合两路检索结果。

        RRF 公式: score = sum(1 / (k + rank_i))
        其中 alpha 控制向量搜索的权重偏好。

        Args:
            bm25_results: BM25 检索结果列表
            vector_results: 向量检索结果列表
            k: RRF 常数（默认60）

        Returns:
            融合后的排序结果
        """
        # 用内容作为去重 key
        content_scores = {}  # content -> {"score": float, "source": str}

        # BM25 结果的 RRF 分数 (权重 = 1 - HYBRID_ALPHA)
        bm25_weight = 1.0 - HYBRID_ALPHA
        for rank, item in enumerate(bm25_results):
            content = item["content"]
            rrf_score = bm25_weight * (1.0 / (k + rank + 1))
            if content in content_scores:
                content_scores[content]["score"] += rrf_score
                content_scores[content]["source"] = "hybrid"
            else:
                content_scores[content] = {"score": rrf_score, "source": "bm25"}

        # 向量结果的 RRF 分数 (权重 = HYBRID_ALPHA)
        for rank, item in enumerate(vector_results):
            content = item["content"]
            rrf_score = HYBRID_ALPHA * (1.0 / (k + rank + 1))
            if content in content_scores:
                content_scores[content]["score"] += rrf_score
                content_scores[content]["source"] = "hybrid"
            else:
                content_scores[content] = {"score": rrf_score, "source": "vector"}

        # 按 RRF 分数降序排列
        merged = [
            {"content": content, "score": info["score"], "source": info["source"]}
            for content, info in content_scores.items()
        ]
        merged.sort(key=lambda x: x["score"], reverse=True)

        return merged

    def _apply_time_decay(self, results: list) -> list:
        """应用时间衰减: final_score = rrf_score * exp(-lambda * days_ago)"""
        now = datetime.utcnow()
        for item in results:
            source = item.get("source", "")
            last_updated = item.get("last_updated")
            if last_updated:
                try:
                    if isinstance(last_updated, str):
                        updated_dt = datetime.fromisoformat(last_updated)
                    else:
                        updated_dt = last_updated
                    days_ago = (now - updated_dt).total_seconds() / 86400.0
                    decay = math.exp(-TIME_DECAY_LAMBDA * max(days_ago, 0))
                    item["score"] = item["score"] * decay
                    item["time_decay"] = round(decay, 4)
                except Exception:
                    pass  # 无法解析时间则不衰减
        results.sort(key=lambda x: x["score"], reverse=True)
        return results

    def _rerank(self, query: str, candidates: list, top_k: int = 5) -> list:
        """
        使用 CrossEncoder 对候选结果进行精排。

        Args:
            query: 查询文本
            candidates: 候选结果列表
            top_k: 返回前 top_k 个结果

        Returns:
            精排后的结果列表
        """
        if not self.rerank_model or not candidates:
            return candidates[:top_k]

        try:
            # 构造 (query, document) 对
            pairs = [(query, item["content"]) for item in candidates]

            # CrossEncoder 打分
            scores = self.rerank_model.predict(pairs)

            # 将 rerank 分数赋给候选结果
            for i, item in enumerate(candidates):
                item["score"] = float(scores[i])

            # 按 rerank 分数降序排列
            candidates.sort(key=lambda x: x["score"], reverse=True)

            return candidates[:top_k]
        except Exception as e:
            logger.warning("[HybridSearch] Rerank 执行失败，返回原始排序: %s", e)
            return candidates[:top_k]
