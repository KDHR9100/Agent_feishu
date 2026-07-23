import os
import sys
sys.path.insert(0, '/home/huajuanx/Agent_feishu')

from dotenv import load_dotenv
load_dotenv()

from app.rag.vectorstore import vector_store

print("=== Testing RAG VectorStore ===")
print(f"VectorStore instance: {type(vector_store).__name__}")
print(f"Embeddings: {type(vector_store.embeddings).__name__}")
print(f"Vector store: {type(vector_store.vector_store).__name__}")

try:
    docs = vector_store.similarity_search("hello", k=2)
    print(f"Found {len(docs)} docs")
    if docs:
        for i, doc in enumerate(docs):
            print(f"Doc {i+1}: {doc.page_content[:50]}...")
    print("VectorStore search successful")
except Exception as e:
    print(f"VectorStore search failed: {e}")

print("\n=== Testing File Upload/Parse ===")
from app.tools.feishu_tool import FeishuTool
tool = FeishuTool()

test_file_path = '/home/huajuanx/Agent_feishu/app/config.py'
try:
    with open(test_file_path, 'rb') as f:
        content = f.read()
    print(f"Binary file read: {len(content)} bytes")
    
    text = content.decode('utf-8')
    print(f"Decoded text: {len(text)} chars")
    print("File parsing successful")
except Exception as e:
    print(f"File parsing failed: {e}")

print("\n=== Done ===")