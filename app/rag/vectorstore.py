from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from typing import List, Optional
import os
import logging
import functools
from concurrent.futures import ThreadPoolExecutor, TimeoutError

os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_DATASETS_OFFLINE"] = "1"

from app.config import config, logger

def timeout(seconds=300):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(func, *args, **kwargs)
                try:
                    return future.result(timeout=seconds)
                except TimeoutError:
                    logger.error("[Timeout] Function %s timed out after %d seconds" % (func.__name__, seconds))
                    raise
        return wrapper
    return decorator

def find_cached_model_path(model_name):
    cache_dir = os.path.expanduser("~/.cache/huggingface/hub")
    model_folder = "models--" + model_name.replace("/", "--")
    model_path = os.path.join(cache_dir, model_folder)
    
    if os.path.exists(model_path):
        snapshots_dir = os.path.join(model_path, "snapshots")
        if os.path.exists(snapshots_dir):
            snapshots = [f for f in os.listdir(snapshots_dir) if os.path.isdir(os.path.join(snapshots_dir, f))]
            if snapshots:
                return os.path.join(snapshots_dir, snapshots[0])
    
    return None

class VectorStore:
    def __init__(self):
        self.embeddings = None
        self.vector_store = None
        self.index_path = "./data/vectorstore/faiss_index"

    @timeout(300)
    def _load_embedding_model(self):
        try:
            if config.USE_LOCAL_EMBEDDING:
                model_name = config.LOCAL_EMBEDDING_MODEL
                logger.info("Loading local embedding model: %s" % model_name)
                
                cached_path = find_cached_model_path(model_name)
                
                if cached_path:
                    logger.info("Using cached model from: %s" % cached_path)
                    model_name_or_path = cached_path
                else:
                    logger.warning("Model not found in cache, trying to download")
                    model_name_or_path = model_name
                
                try:
                    from langchain_huggingface import HuggingFaceEmbeddings
                    self.embeddings = HuggingFaceEmbeddings(
                        model_name=model_name_or_path,
                        model_kwargs={"device": "cpu"},
                        encode_kwargs={"normalize_embeddings": True}
                    )
                    logger.info("Loaded HuggingFaceEmbeddings model: %s" % model_name)
                except ImportError:
                    from langchain_community.embeddings import HuggingFaceEmbeddings
                    self.embeddings = HuggingFaceEmbeddings(
                        model_name=model_name_or_path,
                        model_kwargs={"device": "cpu"},
                        encode_kwargs={"normalize_embeddings": True}
                    )
                    logger.info("Loaded sentence-transformers Embeddings: %s" % model_name)
                return True
            else:
                logger.info("Using API-based embedding: %s" % config.EMBEDDING_MODEL_NAME)
                from langchain_openai import OpenAIEmbeddings
                self.embeddings = OpenAIEmbeddings(
                    model=config.EMBEDDING_MODEL_NAME,
                    api_key=config.EMBEDDING_API_KEY,
                    base_url=config.EMBEDDING_API_BASE,
                )
                logger.info("Loaded API Embeddings: %s" % config.EMBEDDING_MODEL_NAME)
                return True
        except Exception as e:
            logger.error("Failed to load embedding model: %s" % str(e))
            logger.warning("Falling back to MockEmbeddings")
            from langchain_core.embeddings import Embeddings
            import numpy as np
            class MockEmbeddings(Embeddings):
                def embed_documents(self, texts):
                    return [np.random.rand(768).tolist() for _ in texts]
                def embed_query(self, text):
                    return np.random.rand(768).tolist()
            self.embeddings = MockEmbeddings()
            logger.info("Using MockEmbeddings for testing")
            return True

    def initialize(self, documents=None):
        try:
            if not self.embeddings:
                if not self._load_embedding_model():
                    return self

            if os.path.exists(self.index_path) and os.path.isdir(self.index_path):
                logger.info("Loading existing FAISS index from %s" % self.index_path)
                self.vector_store = FAISS.load_local(
                    self.index_path,
                    self.embeddings,
                    allow_dangerous_deserialization=True
                )
                logger.info("FAISS index loaded successfully")
            else:
                if documents:
                    logger.info("Creating new FAISS index from %d documents" % len(documents))
                    self.vector_store = FAISS.from_documents(documents, self.embeddings)
                else:
                    texts = [
                        "E-commerce product analysis and sales forecasting",
                        "Digital marketing and advertising performance optimization",
                        "Content creation for product promotion and brand building",
                        "Customer behavior analysis and user segmentation",
                        "Inventory management and supply chain optimization",
                        "Pricing strategy and competitive analysis",
                        "Social media marketing and engagement metrics",
                        "Conversion rate optimization and A/B testing"
                    ]
                    logger.info("Creating new FAISS index from default texts")
                    self.vector_store = FAISS.from_texts(texts, self.embeddings)
                self.save_local()
                logger.info("FAISS index saved to %s" % self.index_path)

            logger.info("VectorStore initialized successfully")
        except Exception as e:
            logger.error("Failed to initialize VectorStore: %s" % str(e))
        return self

    def add_documents(self, documents):
        if self.vector_store:
            self.vector_store.add_documents(documents)
            self.save_local()

    def add_texts(self, texts, metadatas=None):
        if self.vector_store:
            self.vector_store.add_texts(texts, metadatas)
            self.save_local()

    def similarity_search(self, query, k=3):
        if self.vector_store:
            return self.vector_store.similarity_search(query, k=k)
        return []

    def save_local(self, path=None):
        if self.vector_store:
            save_path = path or self.index_path
            os.makedirs(save_path, exist_ok=True)
            self.vector_store.save_local(save_path)

    def load_local(self, path=None):
        load_path = path or self.index_path
        if os.path.exists(load_path):
            self.vector_store = FAISS.load_local(load_path, self.embeddings, allow_dangerous_deserialization=True)


vector_store = VectorStore()