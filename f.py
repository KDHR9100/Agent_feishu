import sys

with open('app/skills/content_skill.py', 'r') as f:
    content = f.read()

content = content.replace(', '.join(platform_config['features']), ', '.join(str(x) for x in platform_config['features']))
content = content.replace(', '.join(template_config['structure']), ', '.join(str(x) for x in template_config['structure']))

with open('app/skills/content_skill.py', 'w') as f:
    f.write(content)
print('content_skill fixed')

with open('app/tools/feishu_ws.py', 'r') as f:
    content = f.read()

content = content.replace('message_queue = queue.Queue()', 'message_queue: queue.Queue = queue.Queue()')

with open('app/tools/feishu_ws.py', 'w') as f:
    f.write(content)
print('feishu_ws fixed')

with open('app/agents/product_agent.py', 'r') as f:
    content = f.read()

content = content.replace('from langchain_core', 'from typing import Any\nfrom langchain_core')
content = content.replace('def analyze(self, query: str) -> dict:', 'def analyze(self, query: str) -> Any:')

with open('app/agents/product_agent.py', 'w') as f:
    f.write(content)
print('product_agent fixed')

with open('app/agents/ads_agent.py', 'r') as f:
    content = f.read()

content = content.replace('from langchain_core', 'from typing import Any\nfrom langchain_core')
content = content.replace('def analyze(self, query: str) -> dict:', 'def analyze(self, query: str) -> Any:')

with open('app/agents/ads_agent.py', 'w') as f:
    f.write(content)
print('ads_agent fixed')

print('Done')
