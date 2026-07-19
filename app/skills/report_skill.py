from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import config
from app.prompts import SUMMARIZATION_PROMPT
from app.tools.file_tool import file_tool


def report_skill(user_input: str, tool_result: dict = None):
    llm = ChatOpenAI(
        model=config.OPENAI_MODEL_NAME,
        temperature=config.LLM_TEMPERATURE,
        max_tokens=config.LLM_MAX_TOKENS,
        api_key=config.OPENAI_API_KEY,
        base_url=config.OPENAI_API_BASE,
    )
    
    prompt = SUMMARIZATION_PROMPT.format(
        user_input=user_input,
        tool_result=tool_result or "鏆傛棤宸ュ叿鎵ц缁撴灉"
    )
    
    messages = [
        SystemMessage(content="浣犳槸涓€涓笓涓氱殑鎶ュ憡鐢熸垚涓撳"),
        HumanMessage(content=prompt),
    ]
    
    summary = llm.invoke(messages).content
    
    import datetime
    report_content = f"""# 鐢靛晢杩愯惀鍒嗘瀽鎶ュ憡

## 鐢ㄦ埛闇€姹?{user_input}

## 鍒嗘瀽缁撴灉
{summary}

## 鐢熸垚鏃堕棿
{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    
    file_result = file_tool.write_file(
        f"reports/report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
        report_content,
        format_type="text"
    )
    
    return {
        "type": "鎶ュ憡鐢熸垚",
        "data": {
            "summary": summary,
            "report_file": file_result.get("path", ""),
            "success": file_result.get("success", False)
        }
    }
