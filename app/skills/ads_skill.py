from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import config
from app.prompts import ADS_ANALYSIS_PROMPT
from app.tools.database_tool import db_tool


def ads_skill(user_input: str):
    llm = ChatOpenAI(
        model=config.OPENAI_MODEL_NAME,
        temperature=config.LLM_TEMPERATURE,
        max_tokens=config.LLM_MAX_TOKENS,
        api_key=config.OPENAI_API_KEY,
        base_url=config.OPENAI_API_BASE,
    )
    
    try:
        db_data = db_tool.get_ads_performance()
    except Exception as e:
        db_data = {"error": str(e)}
    
    mock_data = {
        "ROI": "1.8",
        "cost": "涓嬮檷15%",
        "suggestion": "浼樺寲鎶曟斁绱犳潗"
    }
    
    combined_data = {
        "database_data": db_data,
        "mock_data": mock_data,
        "user_input": user_input
    }
    
    prompt = ADS_ANALYSIS_PROMPT.format(data=combined_data)
    
    messages = [
        SystemMessage(content="浣犳槸涓€涓數鍟嗗箍鍛婃姇鏀惧垎鏋愪笓瀹?),
        HumanMessage(content=prompt),
    ]
    
    analysis = llm.invoke(messages).content
    
    return {
        "type": "骞垮憡鍒嗘瀽",
        "data": {
            "raw_data": combined_data,
            "analysis": analysis
        }
    }
