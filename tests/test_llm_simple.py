import sys
import os
sys.path.insert(0, '/home/huajuanx/Agent_feishu')

from dotenv import load_dotenv
load_dotenv('/home/huajuanx/Agent_feishu/.env', override=True)

print('=' * 50)
print('LLM CONNECTION TEST')
print('=' * 50)
print('MODEL:', os.environ.get('OPENAI_MODEL_NAME'))
print('API BASE:', os.environ.get('OPENAI_API_BASE'))

try:
    from app.config import get_llm
    llm = get_llm()
    
    from langchain_core.messages import HumanMessage, SystemMessage
    messages = [
        SystemMessage(content='You are a helpful assistant.'),
        HumanMessage(content='Hello, say hi!'),
    ]
    
    response = llm.invoke(messages)
    
    if hasattr(response, 'content'):
        print('SUCCESS:', response.content[:50])
    else:
        print('SUCCESS:', str(response)[:50])
        
except Exception as e:
    print('FAILED:', e)
