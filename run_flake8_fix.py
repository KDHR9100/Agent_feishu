import os

files = {
    '/home/huajuanx/Agent_feishu/app/agents/ads_agent.py': '''from typing import Any
from langchain_core.messages import HumanMessage, SystemMessage
from app.config import get_llm
from app.tools.database_tool import db_tool


class AdsAgent:
    def __init__(self):
        self.llm = get_llm()
        self.role = 'Advertising Analysis Expert'

    def analyze(self, query: str) -> Any:
        data = None
        try:
            data = db_tool.get_ads_performance()
        except Exception as e:
            data = {'error': str(e)}  # type: ignore

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
''',
    '/home/huajuanx/Agent_feishu/app/agents/content_agent.py': '''from langchain_core.messages import HumanMessage, SystemMessage
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
''',
    '/home/huajuanx/Agent_feishu/app/agents/product_agent.py': '''from typing import Any
from langchain_core.messages import HumanMessage, SystemMessage
from app.config import get_llm
from app.tools.database_tool import db_tool


class ProductAgent:
    def __init__(self):
        self.llm = get_llm()
        self.role = 'Product Analysis Expert'

    def analyze(self, query: str) -> Any:
        data = None
        try:
            data = db_tool.get_product_sales()
        except Exception as e:
            data = {'error': str(e)}  # type: ignore

        prompt = 'You are ' + self.role + '. Analyze product sales data: ' + str(data) + '. User query: ' + query
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
''',
    '/home/huajuanx/Agent_feishu/app/agents/coordinator.py': '''from langchain_core.messages import HumanMessage, SystemMessage
from app.config import get_llm
from app.agents.product_agent import ProductAgent
from app.agents.ads_agent import AdsAgent
from app.agents.content_agent import ContentAgent


class Coordinator:
    def __init__(self):
        self.llm = get_llm()
        self.agents = {
            'product': ProductAgent(),
            'ads': AdsAgent(),
            'content': ContentAgent(),
        }

    def route_and_coordinate(self, query: str) -> dict:
        route_prompt = 'Task coordination: analyze user request to determine which agents to call. Request: ' + query + '. Agents: product(Product), ads(Advertising), content(Copy). Return JSON with agents list and reason.'
        messages = [
            SystemMessage(content='You are a task coordination expert'),
            HumanMessage(content=route_prompt),
        ]
        response = self.llm.invoke(messages)

        try:
            import json
            result = json.loads(response.content)
            selected_agents = result.get('agents', [])
            reason = result.get('reason', '')
        except Exception:
            selected_agents = ['product']
            reason = 'Default'

        results = []
        for agent_name in selected_agents:
            if agent_name in self.agents:
                agent = self.agents[agent_name]
                if agent_name == 'content':
                    result = agent.generate(query)
                else:
                    result = agent.analyze(query)
                results.append(result)

        summary_prompt = 'Summarize these expert results: ' + str(results) + '. User request: ' + query
        messages = [
            SystemMessage(content='You are a summary writing expert'),
            HumanMessage(content=summary_prompt),
        ]
        summary = self.llm.invoke(messages).content

        return {
            'query': query,
            'selected_agents': selected_agents,
            'reason': reason,
            'agent_results': results,
            'summary': summary
        }


coordinator = Coordinator()
''',
}

for path, content in files.items():
    with open(path, 'w') as f:
        f.write(content)
    print(f'Fixed: {os.path.basename(path)}')

print('All agent files fixed!')
