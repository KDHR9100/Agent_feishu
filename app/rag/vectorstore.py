from langchain_community.vectorstores import FAISS
from langchain_core.embeddings import Embeddings

import os
import functools
from concurrent.futures import ThreadPoolExecutor, TimeoutError

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
                    logger.error("%s timeout", func.__name__)
                    raise

        return wrapper

    return decorator


def find_cached_model_path(model_name):

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


class MockEmbedding(Embeddings):

    def embed_documents(self, texts):

        return [[0.0] * 768 for _ in texts]

    def embed_query(self, text):

        return [0.0] * 768


class VectorStore:

    def __init__(self):

        self.embeddings = None

        self.vector_store = None

        self.index_path = "./data/vectorstore/faiss_index"

    @timeout(300)
    def load_embeddings(self):

        # ======================
        # 1 Local embedding
        # ======================

        if config.USE_LOCAL_EMBEDDING:

            try:

                model = config.LOCAL_EMBEDDING_MODEL

                logger.info("Loading local embedding: %s", model)

                from langchain_huggingface import HuggingFaceEmbeddings

                path = find_cached_model_path(model)

                if path:

                    model_path = path

                    logger.info("Using cached model %s", path)

                else:

                    model_path = model

                    logger.warning("Model cache missing, loading online")

                self.embeddings = HuggingFaceEmbeddings(
                    model_name=model_path,
                    model_kwargs={"device": "cpu"},
                    encode_kwargs={"normalize_embeddings": True},
                )

                logger.info("Local embedding loaded")

                return True

            except Exception as e:

                logger.error("Local embedding failed: %s", e)

        # ======================
        # 2 DashScope embedding
        # ======================

        try:

            logger.info("Trying DashScope embedding")

            from langchain_community.embeddings import DashScopeEmbeddings

            self.embeddings = DashScopeEmbeddings(
                model=config.EMBEDDING_MODEL_NAME,
                dashscope_api_key=config.EMBEDDING_API_KEY,
            )

            logger.info("DashScope embedding loaded")

            return True

        except Exception as e:

            logger.error("DashScope embedding failed: %s", e)

        except Exception as e:

            logger.error("API embedding failed:%s", e)

        # ======================
        # 3 Mock
        # ======================

        logger.warning("Using MockEmbedding")

        self.embeddings = MockEmbedding()

        return True

    def initialize(self, documents=None):

        try:

            if not self.embeddings:

                self.load_embeddings()

            if os.path.exists(self.index_path):

                logger.info("Loading FAISS index")

                self.vector_store = FAISS.load_local(
                    self.index_path,
                    self.embeddings,
                    allow_dangerous_deserialization=True,
                )

            else:

                logger.info("Creating FAISS index")

                texts = [
                    "商品销量分析",
                    "广告投放ROI分析",
                    "库存管理",
                    "电商运营",
                    "营销内容生成",
                ]

                self.vector_store = FAISS.from_texts(texts, self.embeddings)

                self.save_local()

            logger.info("VectorStore ready")

        except Exception as e:

            logger.error("VectorStore init failed:%s", e)

        return self

    def similarity_search(self, query, k=3):

        if self.vector_store:

            return self.vector_store.similarity_search(query, k=k)

        return []

    def save_local(self):

        if self.vector_store:

            os.makedirs(self.index_path, exist_ok=True)

            self.vector_store.save_local(self.index_path)


vector_store = VectorStore()


def get_vectorstore():
    return vector_store
