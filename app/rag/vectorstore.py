from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from typing import List, Optional

from app.config import config


class VectorStore:
    def __init__(self):
        self.embeddings = OpenAIEmbeddings(
            api_key=config.OPENAI_API_KEY,
            base_url=config.OPENAI_API_BASE,
        )
        self.vector_store = None

    def initialize(self, documents=None):
        if documents:
            self.vector_store = FAISS.from_documents(documents, self.embeddings)
        else:
            texts = ["e-commerce knowledge", "product analysis", "ad strategy", "copywriting"]
            self.vector_store = FAISS.from_texts(texts, self.embeddings)
        return self

    def add_documents(self, documents):
        if self.vector_store:
            self.vector_store.add_documents(documents)

    def add_texts(self, texts, metadatas=None):
        if self.vector_store:
            self.vector_store.add_texts(texts, metadatas)

    def similarity_search(self, query, k=3):
        if self.vector_store:
            return self.vector_store.similarity_search(query, k=k)
        return []

    def save_local(self, path="./rag/faiss_index"):
        if self.vector_store:
            self.vector_store.save_local(path)

    def load_local(self, path="./rag/faiss_index"):
        self.vector_store = FAISS.load_local(path, self.embeddings, allow_dangerous_deserialization=True)


vector_store = VectorStore().initialize()