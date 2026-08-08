import logging
import os
from datetime import datetime
from app.config import get_llm
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger("file_analysis_skill")

# P9: 图片扩展名 (与 file_parser_tool 保持一致)
_IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp'}


def _empty_file_diagnosis(file_path):
    """P9: 文件内容缺失时, 按文件类型给出针对性诊断与建议"""
    if not file_path:
        return ("未收到文件内容（上传可能中断），请重新发送文件。"
                "若多次失败，可尝试更换文件格式（如另存为 CSV/Excel）后重传。")
    ext = os.path.splitext(file_path)[1].lower()
    name = os.path.basename(file_path)
    if ext == '.pdf':
        reason = "该 PDF 可能是扫描件（无文字层），或文件损坏/加密"
        advice = "请导出文字版 PDF，或将关键页截图为图片后重新上传"
    elif ext in ('.xlsx', '.xls', '.csv'):
        reason = "该表格文件可能为空、已损坏，或格式无法解析（如加密、特殊编码）"
        advice = "请确认文件内有数据后，重新导出为 CSV/Excel 再上传"
    elif ext in _IMAGE_EXTS:
        reason = "该图片未能识别出有效内容（可能模糊或识别服务未配置）"
        advice = "请上传更清晰的截图，或将图中表格转为 Excel/CSV 后上传"
    elif ext == '.docx':
        reason = "该 Word 文档未能提取到有效文字（可能损坏或格式不支持）"
        advice = "可将文字内容直接粘贴到消息中发送，或转存为 PDF 后重新上传"
    else:
        reason = "该文件类型（%s）可能不受支持或文件已损坏" % (ext or "未知")
        advice = "请转换为 CSV/Excel/PDF/Word/图片 之一后重新上传"
    return ("⚠️ 文件解析失败：%s\n【可能原因】%s\n【建议】%s" % (name, reason, advice))


def file_analysis_skill(
    user_input: str, file_path: str = None, file_content: str = None
) -> dict:
    """
    文件解析技能：接收文件路径和已解析的内容，生成结构化分析报告
    """
    if not file_content:
        return {
            "type": "file_analysis",
            "data": _empty_file_diagnosis(file_path),
        }

    # P9: 解析成功但 0 行数据 —— 显式报空, 不把空表丢给 LLM 硬分析
    if "行数: 0" in file_content:
        return {
            "type": "file_analysis",
            "data": (
                "⚠️ 文件解析成功，但 **0 行数据**（空表）。\n"
                "请确认文件内是否确实有数据：\n"
                "1. 若文件本身是空模板，请填充数据后重新上传；\n"
                "2. 若数据在其它工作表（Sheet），请将该工作表单独导出为 CSV/Excel 后重新上传。"
            ),
        }

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    system_prompt = (
        "你是一个专业的数据分析师。用户上传了一个数据文件，以下是文件的解析结果。\n"
        "请根据文件内容，为用户提供有价值的分析，包括：\n"
        "1. 数据概况总结（包含哪些字段、数据量等）\n"
        "2. 关键数据洞察（如趋势、异常值、高价值信息等）\n"
        "3. 针对电商业务场景的建议（如适用）\n"
        "4. 如果有用户的具体问题，针对性回答\n\n"
        "请用清晰、专业但易懂的中文回复。如果数据中有表格，适当引用具体数值。\n"
        "回复格式要求：使用 Markdown 格式，包含标题、分段、适当使用 Emoji 让报告更易读。"
    )

    user_prompt = f"""用户的问题：{user_input if user_input else "请分析这份数据"}

以下是文件解析结果：
{file_content}

请根据以上数据进行分析和回答。如果用户的问题不明确，给出数据概括和建议。"""

    try:
        llm = get_llm()
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        response = llm.invoke(messages)

        reply = response.content if hasattr(response, "content") else str(response)

        # 记录 token 使用
        if hasattr(response, "response_metadata") and response.response_metadata:
            token_usage = response.response_metadata.get("token_usage", {})
            logger.info(
                "[FileAnalysisSkill] Token Usage - Prompt: %d, Completion: %d, Total: %d"
                % (
                    token_usage.get("prompt_tokens", 0),
                    token_usage.get("completion_tokens", 0),
                    token_usage.get("total_tokens", 0),
                )
            )

        # 结构化包装回复
        separator = '\u2500' * 30
        formatted_reply = (
            f"\U0001f4ca **数据分析报告**\n"
            f"\U0001f550 生成时间：{timestamp}\n"
            f"{separator}\n\n"
            f"{reply}\n\n"
            f"{separator}\n"
            f"\U0001f4a1 如需进一步分析，请随时告诉我。"
        )

        return {"type": "file_analysis", "data": formatted_reply}

    except Exception as e:
        logger.error("[FileAnalysisSkill] Error: %s" % str(e))
        return {
            "type": "file_analysis",
            "data": "分析文件时出错，请稍后重试或检查文件格式。",
        }


file_analysis_skill = file_analysis_skill
