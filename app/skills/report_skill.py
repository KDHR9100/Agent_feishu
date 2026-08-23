from langchain_core.messages import HumanMessage, SystemMessage
import datetime
from typing import Optional, Dict, Any

from app.config import get_llm, logger
from app.prompts import SUMMARIZATION_PROMPT
from app.tools.file_tool import file_tool
from app.utils.time_utils import parse_time_range


def _collect_report_data(start_date: datetime.date, end_date: datetime.date) -> Dict[str, Any]:
    """根据日期范围从 CSV 收集数据"""
    try:
        from app.tools.database_tool import db_tool

        start_str = start_date.isoformat()
        end_str = end_date.isoformat()

        data_parts = []

        # 读取并过滤商品销售数据
        all_products = db_tool.read_data("product_sales.csv")
        filtered_products = [
            r for r in all_products
            if start_str <= str(r.get("date", "")) <= end_str
        ]
        if filtered_products:
            data_parts.append(f"【商品销售数据】\n{filtered_products}")

        # 读取并过滤广告投放数据
        all_ads = db_tool.read_data("ads_performance.csv")
        filtered_ads = [
            r for r in all_ads
            if start_str <= str(r.get("date", "")) <= end_str
        ]
        if filtered_ads:
            data_parts.append(f"【广告投放数据】\n{filtered_ads}")

        return {
            "has_data": bool(data_parts),
            "data": "\n\n".join(data_parts) if data_parts else "",
        }
    except Exception as e:
        logger.warning("[report_skill] 数据收集失败: %s", e)
        return {"has_data": False, "data": "", "error": str(e)}


def report_skill(user_input: str, tool_result: Optional[dict] = None):
    # 1. 解析时间范围
    start_date, end_date, time_desc = parse_time_range(user_input)

    # 2. 收集实际数据
    db_data = _collect_report_data(start_date, end_date)

    # 3. 无数据时直接返回提示，不调 LLM，避免幻觉
    if not db_data.get("has_data"):
        no_data_msg = (
            f"抱歉，{time_desc}暂无可用于生成运营报告的数据。"
            "目前支持的数据包括：商品销售数据、广告投放数据。"
            "请先确保相关数据已导入系统，之后我就可以为您生成运营报告了。"
        )
        return {
            "type": "report_generation",
            "data": {
                "summary": no_data_msg,
                "report_file": "",
                "success": False,
                "no_data": True,
            },
        }

    # 4. 有数据时，构建 prompt 调用 LLM 生成报告
    llm = get_llm()

    tool_info = f"报告时间范围：{time_desc}\n当前日期：{datetime.date.today()}"
    if db_data.get("data"):
        tool_info += f"\n\n实际业务数据：\n{db_data['data']}"
    if tool_result:
        tool_info += f"\n\n其他工具结果：{tool_result}"

    prompt = SUMMARIZATION_PROMPT.format(
        user_input=user_input, tool_result=tool_info
    )

    messages = [
        SystemMessage(content="You are a professional summary generation expert"),
        HumanMessage(content=prompt),
    ]

    summary = llm.invoke(messages).content

    report_content = (
        f"# 运营报告（{time_desc}）\n\n## 用户需求\n"
        + user_input
        + "\n\n## 分析结果\n"
        + summary
        + "\n\n## 生成时间\n"
        + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        + "\n"
    )

    file_result = file_tool.write_file(
        "reports/report_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".md",
        report_content,
        format_type="text",
    )

    return {
        "type": "report_generation",
        "data": {
            "summary": summary,
            "report_file": file_result.get("path", ""),
            "success": file_result.get("success", False),
        },
    }
