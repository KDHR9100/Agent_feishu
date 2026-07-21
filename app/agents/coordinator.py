from langchain_core.messages import HumanMessage, SystemMessage
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
