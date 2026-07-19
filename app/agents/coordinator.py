from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import config
from app.agents.product_agent import ProductAgent
from app.agents.ads_agent import AdsAgent
from app.agents.content_agent import ContentAgent


class Coordinator:
    def __init__(self):
        self.llm = ChatOpenAI(
            model=config.OPENAI_MODEL_NAME,
            temperature=config.LLM_TEMPERATURE,
            max_tokens=config.LLM_MAX_TOKENS,
            api_key=config.OPENAI_API_KEY,
            base_url=config.OPENAI_API_BASE,
        )
        
        self.agents = {
            "product": ProductAgent(),
            "ads": AdsAgent(),
            "content": ContentAgent(),
        }
    
    def route_and_coordinate(self, query: str) -> dict:
        route_prompt = f"""浣犳槸涓€涓换鍔″崗璋冧笓瀹躲€傝鍒嗘瀽鐢ㄦ埛闇€姹傦紝鍐冲畾闇€瑕佽皟鐢ㄥ摢浜涗笓瀹禔gent銆?
鐢ㄦ埛闇€姹傦細{query}

鍙敤Agent锛?1. product - 鍟嗗搧鍒嗘瀽涓撳
2. ads - 骞垮憡鍒嗘瀽涓撳
3. content - 钀ラ攢鏂囨涓撳

杩斿洖鏍煎紡锛圝SON锛夛細
{{
    "agents": ["agent_name1", "agent_name2"],
    "reason": "閫夋嫨鍘熷洜"
}}
"""
        
        messages = [
            SystemMessage(content="浣犳槸浠诲姟鍗忚皟涓撳"),
            HumanMessage(content=route_prompt),
        ]
        
        response = self.llm.invoke(messages)
        
        try:
            import json
            result = json.loads(response.content)
            selected_agents = result.get("agents", [])
            reason = result.get("reason", "")
        except:
            selected_agents = ["product"]
            reason = "榛樿閫夋嫨鍟嗗搧鍒嗘瀽"
        
        results = []
        for agent_name in selected_agents:
            if agent_name in self.agents:
                agent = self.agents[agent_name]
                if agent_name == "content":
                    result = agent.generate(query)
                else:
                    result = agent.analyze(query)
                results.append(result)
        
        summary_prompt = f"""璇锋眹鎬讳互涓嬩笓瀹剁殑鍒嗘瀽缁撴灉锛岀敓鎴愪竴浠界患鍚堟姤鍛娿€?
鐢ㄦ埛闇€姹傦細{query}

涓撳鍒嗘瀽缁撴灉锛?{results}

璇风敤鑷劧銆佸弸濂界殑璇█鎬荤粨缁欑敤鎴枫€?"""
        
        messages = [
            SystemMessage(content="浣犳槸鎶ュ憡姹囨€讳笓瀹?),
            HumanMessage(content=summary_prompt),
        ]
        
        summary = self.llm.invoke(messages).content
        
        return {
            "query": query,
            "selected_agents": selected_agents,
            "reason": reason,
            "agent_results": results,
            "summary": summary
        }


coordinator = Coordinator()
