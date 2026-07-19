from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import config
from app.tools.database_tool import db_tool


class ProductAgent:
    def __init__(self):
        self.llm = ChatOpenAI(
            model=config.OPENAI_MODEL_NAME,
            temperature=config.LLM_TEMPERATURE,
            max_tokens=config.LLM_MAX_TOKENS,
            api_key=config.OPENAI_API_KEY,
            base_url=config.OPENAI_API_BASE,
        )
        self.role = "鍟嗗搧鍒嗘瀽涓撳"
    
    def analyze(self, query: str) -> dict:
        try:
            data = db_tool.get_product_sales()
        except Exception as e:
            data = {"error": str(e)}
        
        prompt = f"""浣犳槸{self.role}銆傝鏍规嵁鍟嗗搧閿€鍞暟鎹繘琛屽垎鏋愩€?
鏁版嵁锛歿data}

鐢ㄦ埛鏌ヨ锛歿query}

璇锋彁渚涗笓涓氱殑鍟嗗搧鍒嗘瀽鎶ュ憡銆?"""
        
        messages = [
            SystemMessage(content=f"浣犳槸{self.role}"),
            HumanMessage(content=prompt),
        ]
        
        response = self.llm.invoke(messages)
        
        return {
            "agent": self.role,
            "query": query,
            "data": data,
            "analysis": response.content
        }
