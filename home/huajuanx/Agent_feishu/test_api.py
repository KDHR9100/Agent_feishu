import requests
import json

url = "http://127.0.0.1:8000"

print("TEST 1: /health")
r = requests.get(url + "/health")
print(r.status_code, r.json().get("status"))

print("\nTEST 2: /chat")
r = requests.post(url + "/chat", json={"message": "Hello"}, timeout=30)
print(r.status_code)

print("\nTEST 3: /feishu/webhook")
payload = {"schema": "2.0", "header": {"event_type": "im.message.receive_v1"}, "event": {"message": {"content": json.dumps({"text": "test"})}}}
r = requests.post(url + "/feishu/webhook", json=payload, timeout=30)
print(r.status_code)

print("\nAll tests done!")
