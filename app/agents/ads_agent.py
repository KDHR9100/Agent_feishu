from langchain_core.messages import HumanMessage, SystemMessage
from app.config import get_llm
from app.tools.database_tool import db_tool

class AdsAgent:
    def __init__(self):
        self.llm = get_llm()
        self.role = 'Advertising Analysis Expert'
    
    def analyze(self, query: str) -> dict:
        try:
            data = db_tool.get_ads_performance()
        except Exception as e:
            data = {'error': str(e)}
        
        prompt = 'You are ' + self.role + '. Analyze ad performance data: ' + str(data) + '. User query: ' + query
        
        messages = [
            SystemMessage(content='You are ' + self.role),
            HumanMessage(content=prompt),
        ]
        
        response = self.llm.invoke(messages)
        
        return {
            'agent': self.role,
            'query': query,
            'data': data,
            'analysis': response.content
        }
