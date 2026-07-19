from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import config


class ContentAgent:
    def __init__(self):
        self.llm = ChatOpenAI(
            model=config.OPENAI_MODEL_NAME,
            temperature=config.LLM_TEMPERATURE,
            max_tokens=config.LLM_MAX_TOKENS,
            api_key=config.OPENAI_API_KEY,
            base_url=config.OPENAI_API_BASE,
        )
        self.role = "钀ラ攢鏂囨涓撳"
    
    def generate(self, query: str) -> dict:
        prompt = f"""浣犳槸{self.role}銆傝鏍规嵁鐢ㄦ埛闇€姹傜敓鎴愯惀閿€鏂囨銆?
鐢ㄦ埛闇€姹傦細{query}

瑕佹眰锛?1. 绗﹀悎鐢靛晢钀ラ攢鍦烘櫙
2. 璇█鐢熷姩鏈夎叮
3. 绐佸嚭浜у搧鍗栫偣
4. 婵€鍙戣喘涔版鏈?"""
        
        messages = [
            SystemMessage(content=f"浣犳槸{self.role}"),
            HumanMessage(content=prompt),
        ]
        
        response = self.llm.invoke(messages)
        
        return {
            "agent": self.role,
            "query": query,
            "copy": response.content
        }
