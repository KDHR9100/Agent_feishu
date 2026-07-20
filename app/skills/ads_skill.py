from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_llm
from app.prompts import ADS_ANALYSIS_PROMPT
from app.tools.database_tool import db_tool


def ads_skill(user_input: str):
    llm = get_llm()
    
    try:
        db_data = db_tool.get_ads_performance()
    except Exception as e:
        db_data = {'error': str(e)}
    
    mock_data = {
        'ROI': '1.8',
        'cost': 'decreased 15%',
        'suggestion': 'optimize ad creatives'
    }
    
    combined_data = {
        'database_data': db_data,
        'mock_data': mock_data,
        'user_input': user_input
    }
    
    prompt = ADS_ANALYSIS_PROMPT.format(data=combined_data)
    
    messages = [
        SystemMessage(content='You are an e-commerce advertising analysis expert'),
        HumanMessage(content=prompt),
    ]
    
    analysis = llm.invoke(messages).content
    
    return {
        'type': 'ads_analysis',
        'data': {
            'raw_data': combined_data,
            'analysis': analysis
        }
    }
