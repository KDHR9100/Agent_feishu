import re
from typing import Any, Dict
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_llm, logger


def extract_file_info(user_input: str) -> Dict[str, str]:
    message_id = re.search(r'message[_-]?id[:\s]*([a-zA-Z0-9_-]+)', user_input, re.IGNORECASE)
    file_token = re.search(r'file[_-]?token[:\s]*([a-zA-Z0-9_-]+)', user_input, re.IGNORECASE)
    file_name = re.search(r'file[_-]?name[:\s]*([^\s]+)', user_input, re.IGNORECASE)
    doc_token = re.search(r'doc[_-]?token[:\s]*([a-zA-Z0-9_-]+)', user_input, re.IGNORECASE)
    
    return {
        'message_id': message_id.group(1) if message_id else '',
        'file_token': file_token.group(1) if file_token else '',
        'file_name': file_name.group(1) if file_name else '',
        'doc_token': doc_token.group(1) if doc_token else '',
        'file_path': '',
    }
