from langchain_core.messages import HumanMessage, SystemMessage
import datetime

from app.config import get_llm
from app.prompts import SUMMARIZATION_PROMPT
from app.tools.file_tool import file_tool


def report_skill(user_input: str, tool_result: dict = None):
    llm = get_llm()
    
    prompt = SUMMARIZATION_PROMPT.format(
        user_input=user_input,
        tool_result=tool_result or 'No tool execution result'
    )
    
    messages = [
        SystemMessage(content='You are a professional summary generation expert'),
        HumanMessage(content=prompt),
    ]
    
    summary = llm.invoke(messages).content
    
    report_content = '# E-commerce Operation Analysis Report

## User Request
' + user_input + '

## Analysis Result
' + summary + '

## Generated Time
' + datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S') + '
'
    
    file_result = file_tool.write_file(
        'reports/report_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S') + '.md',
        report_content,
        format_type='text'
    )
    
    return {
        'type': 'report_generation',
        'data': {
            'summary': summary,
            'report_file': file_result.get('path', ''),
            'success': file_result.get('success', False)
        }
    }
