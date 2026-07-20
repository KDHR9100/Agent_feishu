from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_llm
from app.prompts import CONTENT_GENERATION_PROMPT


def content_skill(user_input: str):
    llm = get_llm()
    
    prompt = CONTENT_GENERATION_PROMPT.format(user_input=user_input)
    
    messages = [
        SystemMessage(content='You are an e-commerce marketing copywriting expert'),
        HumanMessage(content=prompt),
    ]
    
    copy = llm.invoke(messages).content
    
    return {
        'type': 'marketing_copy',
        'data': {
            'user_input': user_input,
            'copy': copy
        }
    }
