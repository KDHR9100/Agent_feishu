from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import config
from app.prompts import PRODUCT_ANALYSIS_PROMPT
from app.tools.product import get_product_sales
from app.tools.database_tool import db_tool


def product_skill(user_input: str):
    llm = ChatOpenAI(
        model=config.OPENAI_MODEL_NAME,
        temperature=config.LLM_TEMPERATURE,
        max_tokens=config.LLM_MAX_TOKENS,
        api_key=config.OPENAI_API_KEY,
        base_url=config.OPENAI_API_BASE,
    )
    
    try:
        db_data = db_tool.get_product_sales()
    except Exception as e:
        db_data = {"error": str(e)}
    
    mock_data = get_product_sales("SKU10086")
    
    combined_data = {
        "database_data": db_data,
        "mock_data": mock_data,
        "user_input": user_input
    }
    
    prompt = PRODUCT_ANALYSIS_PROMPT.format(data=combined_data)
    
    messages = [
        SystemMessage(content="浣犳槸涓€涓數鍟嗗晢鍝佸垎鏋愪笓瀹?),
        HumanMessage(content=prompt),
    ]
    
    analysis = llm.invoke(messages).content
    
    return {
        "type": "鍟嗗搧鍒嗘瀽",
        "data": {
            "raw_data": combined_data,
            "analysis": analysis
        }
    }
