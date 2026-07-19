from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import config
from app.prompts import CONTENT_GENERATION_PROMPT


def content_skill(user_input: str):
    llm = ChatOpenAI(
        model=config.OPENAI_MODEL_NAME,
        temperature=config.LLM_TEMPERATURE,
        max_tokens=config.LLM_MAX_TOKENS,
        api_key=config.OPENAI_API_KEY,
        base_url=config.OPENAI_API_BASE,
    )
    
    prompt = CONTENT_GENERATION_PROMPT.format(user_input=user_input)
    
    messages = [
        SystemMessage(content="浣犳槸涓€涓數鍟嗚惀閿€鏂囨涓撳"),
        HumanMessage(content=prompt),
    ]
    
    copy = llm.invoke(messages).content
    
    return {
        "type": "钀ラ攢鏂囨",
        "data": {
            "user_input": user_input,
            "copy": copy
        }
    }
