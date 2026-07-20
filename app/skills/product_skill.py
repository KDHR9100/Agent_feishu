from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_llm
from app.prompts import PRODUCT_ANALYSIS_PROMPT
from app.tools.database_tool import db_tool


def product_skill(user_input: str):
    llm = get_llm()
    
    try:
        db_data = db_tool.get_product_sales()
    except Exception as e:
        db_data = {'error': str(e)}
    
    mock_data = {
        'SKU': 'SKU10086',
        'product_name': 'Example Product',
        'sales_trend': 'rising',
        'stock_status': 'sufficient'
    }
    
    combined_data = {
        'database_data': db_data,
        'mock_data': mock_data,
        'user_input': user_input
    }
    
    prompt = PRODUCT_ANALYSIS_PROMPT.format(data=combined_data)
    
    messages = [
        SystemMessage(content='You are an e-commerce product analysis expert'),
        HumanMessage(content=prompt),
    ]
    
    analysis = llm.invoke(messages).content
    
    return {
        'type': 'product_analysis',
        'data': {
            'raw_data': combined_data,
            'analysis': analysis
        }
    }
