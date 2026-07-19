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
    
    def initialize(self, documents: Optional[List[Document]] = None):
        if documents:
            self.vector_store = FAISS.from_documents(documents, self.embeddings)
        else:
            self.vector_store = FAISS.from_texts(
                ["鐢靛晢杩愯惀鐭ヨ瘑", "鍟嗗搧鍒嗘瀽鎶€宸?, "骞垮憡鎶曟斁绛栫暐", "钀ラ攢鏂囨鍐欎綔"],
                self.embeddings
            )
        return self
    
    def add_documents(self, documents: List[Document]):
        if self.vector_store:
            self.vector_store.add_documents(documents)
    
    def add_texts(self, texts: List[str], metadatas: Optional[List[dict]] = None):
        if self.vector_store:
            self.vector_store.add_texts(texts, metadatas)
    
    def similarity_search(self, query: str, k: int = 3) -> List[Document]:
        if self.vector_store:
            return self.vector_store.similarity_search(query, k=k)
        return []
    
    def save_local(self, path: str = "./rag/faiss_index"):
        if self.vector_store:
            self.vector_store.save_local(path)
    
    def load_local(self, path: str = "./rag/faiss_index"):
        self.vector_store = FAISS.load_local(
            path,
            self.embeddings,
            allow_dangerous_deserialization=True
        )


vector_store = VectorStore().initialize()
