from langchain.chains import RetrievalQA
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from typing import Optional

from app.config import config
from app.rag.vectorstore import vector_store


class RAGRetriever:
    def __init__(self):
        self.llm = ChatOpenAI(
            model=config.OPENAI_MODEL_NAME,
            temperature=config.LLM_TEMPERATURE,
            max_tokens=config.LLM_MAX_TOKENS,
            api_key=config.OPENAI_API_KEY,
            base_url=config.OPENAI_API_BASE,
        )
        self.retriever = vector_store.vector_store.as_retriever()
    
    def retrieve(self, query: str, k: int = 3) -> list:
        docs = self.retriever.get_relevant_documents(query)
        return docs
    
    def query(self, question: str, context: Optional[str] = None) -> str:
        docs = self.retrieve(question)
        
        context_text = "\n".join([doc.page_content for doc in docs])
        
        if context:
            context_text += "\n" + context
        
        prompt = f"""鍩轰簬浠ヤ笅涓婁笅鏂囦俊鎭洖绛旈棶棰橈細

涓婁笅鏂囷細
{context_text}

闂锛歿question}

璇锋牴鎹笂涓嬫枃淇℃伅鍥炵瓟闂锛屽鏋滀笂涓嬫枃娌℃湁鐩稿叧淇℃伅锛岃鏄庣‘璇存槑銆?"""
        
        messages = [
            SystemMessage(content="浣犳槸涓€涓笓涓氱殑鐢靛晢杩愯惀鍔╂墜"),
            HumanMessage(content=prompt),
        ]
        
        response = self.llm.invoke(messages)
        return response.content
    
    def retrieve_and_generate(self, query: str) -> dict:
        docs = self.retrieve(query)
        
        context_text = "\n".join([doc.page_content for doc in docs])
        
        prompt = f"""鍩轰簬浠ヤ笅鐭ヨ瘑搴撲俊鎭紝涓虹敤鎴锋彁渚涗笓涓氱殑鐢靛晢杩愯惀寤鸿锛?
鐭ヨ瘑搴擄細
{context_text}

鐢ㄦ埛闂锛歿query}

璇锋彁渚涜缁嗐€佷笓涓氱殑鍥炵瓟銆?"""
        
        messages = [
            SystemMessage(content="浣犳槸涓€涓笓涓氱殑鐢靛晢杩愯惀椤鹃棶"),
            HumanMessage(content=prompt),
        ]
        
        response = self.llm.invoke(messages)
        
        return {
            "query": query,
            "retrieved_docs": [doc.page_content for doc in docs],
            "answer": response.content
        }


rag_retriever = RAGRetriever()
