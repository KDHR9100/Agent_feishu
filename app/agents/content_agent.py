from langchain_core.messages import HumanMessage, SystemMessage
from app.config import get_llm


class ContentAgent:
    def __init__(self):
        self.llm = get_llm()
        self.role = 'Marketing Copy Expert'

    def generate(self, query: str) -> dict:
        prompt = 'You are ' + self.role + '. Generate marketing copy for: ' + query
        messages = [
            SystemMessage(content='You are ' + self.role),
            HumanMessage(content=prompt),
        ]
        response = self.llm.invoke(messages)

        return {
            'agent': self.role,
            'query': query,
            'copy': response.content
        }
