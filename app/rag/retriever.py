from langchain_core.messages import HumanMessage, SystemMessage
from typing import Optional

from app.config import get_llm
from app.rag.vectorstore import vector_store

class RAGRetriever:
    def __init__(self):
        self.llm = get_llm()
        self.retriever = vector_store.vector_store.as_retriever()

    def retrieve(self, query: str, k: int = 3) -> list:
        docs = self.retriever.invoke(query)
        return docs

    def query(self, question: str, context: Optional[str] = None) -> str:
        docs = self.retrieve(question)
        context_parts = [doc.page_content for doc in docs]
        if context:
            context_parts.append(context)
