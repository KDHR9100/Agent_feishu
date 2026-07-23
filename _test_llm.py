import os
import sys
sys.path.insert(0, '/home/huajuanx/Agent_feishu')

from dotenv import load_dotenv
load_dotenv()

from app.config import get_llm, config

print(f"Model: {config.LLM_MODEL_NAME}")
print(f"Provider: {config.LLM_PROVIDER}")
print(f"API Base: {config.LLM_API_BASE}")

llm = get_llm()
print(f"LLM object: {type(llm).__name__}")

try:
    result = llm.invoke("请用一句话介绍你自己")
    print("Response:", result.content)
except Exception as e:
    print(f"Error: {e}")