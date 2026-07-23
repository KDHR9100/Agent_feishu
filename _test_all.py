import os
import sys
sys.path.insert(0, '/home/huajuanx/Agent_feishu')

from dotenv import load_dotenv
load_dotenv()

from app.config import get_llm, config

print("=== Configuration ===")
print(f"Model: {config.LLM_MODEL_NAME}")
print(f"Provider: {config.LLM_PROVIDER}")
print(f"API Base: {config.LLM_API_BASE}")
print(f"API Key: {config.LLM_API_KEY[:10]}...")

print("\n=== Testing LLM Call ===")
try:
    llm = get_llm()
    print(f"LLM Type: {type(llm).__name__}")
    
    result = llm.invoke("请用一句话介绍你自己")
    print(f"Response: {result.content}")
    print("LLM call successful")
except Exception as e:
    print(f"LLM call failed: {e}")
    import traceback
    traceback.print_exc()

print("\n=== Testing File Reading ===")
test_file_path = '/home/huajuanx/Agent_feishu/app/config.py'
try:
    with open(test_file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    print(f"Read {len(content)} bytes from {test_file_path}")
    print(f"First 100 chars: {content[:100]}...")
    print("File reading successful")
except Exception as e:
    print(f"File reading failed: {e}")

print("\n=== Testing RAG VectorStore ===")
try:
    from app.rag.vectorstore import get_vectorstore
    vs = get_vectorstore()
    print(f"VectorStore Type: {type(vs).__name__}")
    print("VectorStore loaded successfully")
except Exception as e:
    print(f"VectorStore loading failed: {e}")
    import traceback
    traceback.print_exc()

print("\n=== Testing API Health ===")
import subprocess
try:
    result = subprocess.run(
        ['curl', '-s', '-o', '/dev/null', '-w', '%{http_code}', 'http://localhost:8000/health'],
        capture_output=True,
        timeout=5
    )
    if result.returncode == 0:
        print(f"Health check: HTTP {result.stdout.decode()}")
        print("API server is responsive")
    else:
        print(f"Health check failed: {result.stderr.decode()}")
except Exception as e:
    print(f"Health check exception: {e}")

print("\n=== Done ===")