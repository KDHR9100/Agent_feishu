import re
from typing import Any, Dict

from app.config import get_llm, logger


def extract_file_info(user_input: str) -> Dict[str, str]:
    message_id = re.search(
        r"message[_-]?id[:\s]*([a-zA-Z0-9_-]+)", user_input, re.IGNORECASE
    )
    file_token = re.search(
        r"file[_-]?token[:\s]*([a-zA-Z0-9_-]+)", user_input, re.IGNORECASE
    )
    file_name = re.search(r"file[_-]?name[:\s]*([^\s]+)", user_input, re.IGNORECASE)
    doc_token = re.search(
        r"doc[_-]?token[:\s]*([a-zA-Z0-9_-]+)", user_input, re.IGNORECASE
    )

    return {
        "message_id": message_id.group(1) if message_id else "",
        "file_token": file_token.group(1) if file_token else "",
        "file_name": file_name.group(1) if file_name else "",
        "doc_token": doc_token.group(1) if doc_token else "",
        "file_path": "",
    }


def data_analysis_skill(user_input: str) -> Dict[str, Any]:
    try:
        file_info = extract_file_info(user_input)
        llm = get_llm()
        prompt = f"分析数据: {user_input}"
        response = llm.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        return {
            "type": "data_analysis",
            "data": {
                "user_input": user_input,
                "file_info": file_info,
                "analysis": content[:500],
            },
        }
    except Exception as e:
        logger.error("data_analysis_skill error: %s", e)
        return {
            "type": "data_analysis",
            "data": {
                "user_input": user_input,
                "analysis": "",
                "error": str(e),
            },
        }
