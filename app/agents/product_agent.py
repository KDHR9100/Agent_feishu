from typing import Any
from langchain_core.messages import HumanMessage, SystemMessage
from app.config import get_llm
from app.tools.database_tool import db_tool


class ProductAgent:
    def __init__(self):
        self.llm = get_llm()
        self.role = "Product Analysis Expert"

    def analyze(self, query: str) -> Any:
        data = None
        try:
            data = db_tool.get_product_sales()
        except Exception as e:
            data = {"error": str(e)}  # type: ignore

        prompt = (
            "You are "
            + self.role
            + ". Analyze product sales data: "
            + str(data)
            + ". User query: "
            + query
        )
        messages = [
            SystemMessage(content="You are " + self.role),
            HumanMessage(content=prompt),
        ]
        response = self.llm.invoke(messages)

        return {
            "agent": self.role,
            "query": query,
            "data": data,
            "analysis": response.content,
        }
