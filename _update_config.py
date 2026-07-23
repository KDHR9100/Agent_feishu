import os

config_path = '/home/huajuanx/Agent_feishu/app/config.py'

with open(config_path, 'r', encoding='utf-8-sig') as f:
    content = f.read()

content = content.replace(
    'os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")',
    'os.getenv("OPENAI_API_BASE", "https://api.deepseek.com/v1")'
)
content = content.replace(
    'os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini")',
    'os.getenv("OPENAI_MODEL_NAME", "deepseek-v4-pro")'
)

old_provider = """    @property
    def LLM_PROVIDER(self):
        if "dashscope" in self.LLM_API_BASE.lower():
            return "DashScope"
        elif "openai" in self.LLM_API_BASE.lower():
            return "OpenAI"
        else:
            return "Unknown"
"""

new_provider = """    @property
    def LLM_PROVIDER(self):
        if "deepseek" in self.LLM_API_BASE.lower():
            return "DeepSeek"
        elif "dashscope" in self.LLM_API_BASE.lower():
            return "DashScope"
        elif "openai" in self.LLM_API_BASE.lower():
            return "OpenAI"
        else:
            return "Unknown"
"""

content = content.replace(old_provider, new_provider)

with open(config_path, 'w', encoding='utf-8') as f:
    f.write(content)

print('config.py updated successfully')