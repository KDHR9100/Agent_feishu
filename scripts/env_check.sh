#!/bin/bash
cd /home/huajuanx/Agent_feishu
ls scripts/
echo "=== deps ==="
python3 -c "import requests, fastapi, langchain, langgraph, pandas; print('py3-deps-ok')" 2>&1 | tail -1
echo "=== server ==="
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/health --max-time 3 || echo server-down
