import logging
from app.config import get_llm
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger("file_analysis_skill")


def file_analysis_skill(user_input: str, file_path: str = None, file_content: str = None) -> dict:
    """
    文件解析技能：接收文件路径和已解析的内容，生成分析报告
    """
    if not file_content:
        return {
            "type": "file_analysis",
            "data": "未收到有效的文件内容，请重新上传文件。"
        }

    # 构建分析 prompt
    system_prompt = (
        "你是一个专业的数据分析师。用户上传了一个数据文件，以下是文件的解析结果。\n"
        "请根据文件内容，为用户提供有价值的分析，包括：\n"
        "1. 数据概况总结（包含哪些字段、数据量等）\n"
        "2. 关键数据洞察（如趋势、异常值、高价值信息等）\n"
        "3. 针对电商业务场景的建议（如适用）\n"
        "4. 如果有用户的具体问题，针对性回答\n\n"
        "请用清晰、专业但易懂的中文回复。如果数据中有表格，适当引用具体数值。"
    )

    user_prompt = f"""用户的问题：{user_input if user_input else "请分析这份数据"}

以下是文件解析结果：
{file_content}

请根据以上数据进行分析和回答。如果用户的问题不明确，给出数据概要和建议。"""

    try:
        llm = get_llm()
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        response = llm.invoke(messages)

        reply = response.content if hasattr(response, "content") else str(response)

        # 记录 token 使用（可选）
        if hasattr(response, "response_metadata") and response.response_metadata:
            token_usage = response.response_metadata.get("token_usage", {})
            logger.info("[FileAnalysisSkill] Token Usage - Prompt: %d, Completion: %d, Total: %d" % (
                token_usage.get("prompt_tokens", 0),
                token_usage.get("completion_tokens", 0),
                token_usage.get("total_tokens", 0)
            ))

        return {
            "type": "file_analysis",
            "data": reply
        }

    except Exception as e:
        logger.error("[FileAnalysisSkill] Error: %s" % str(e))
        return {
            "type": "file_analysis",
            "data": f"分析文件时出错：{str(e)}"
        }


# 导出技能实例（可选，保持与项目中其他 skill 一致）
file_analysis_skill = file_analysis_skill