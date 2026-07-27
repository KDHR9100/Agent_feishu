"""数据分析技能 - 支持数据库查询 + 文件数据 + LLM 分析

优化点（相对原始版本）：
1. 集成 database_tool：支持直接查询商品/广告/库存数据
2. 结构化 Prompt：引导 LLM 做专业数据分析而非简单复述
3. 统计摘要：自动计算基础统计指标（均值/总和/趋势）
4. 完整输出：不截断分析结果

使用方式：
    from app.skills.data_analysis_skill import data_analysis_skill
    result = data_analysis_skill("分析最近一周的销量趋势")
"""
from typing import Any, Dict
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_llm, logger

DATA_ANALYSIS_SYSTEM_PROMPT = """你是一个专业的电商数据分析师。
请基于提供的数据，进行深入分析并生成专业报告。

分析要求：
1. 数据概览：关键指标汇总
2. 趋势分析：同比/环比变化
3. 异常检测：识别数据中的异常波动
4. 归因分析：分析变化背后的可能原因
5. 行动建议：给出可执行的优化方案

请使用中文输出，包含具体数据支撑。"""


def _get_db_data(user_input: str) -> Dict[str, Any]:
    """尝试从数据库获取相关数据"""
    try:
        from app.tools.database_tool import db_tool

        data_parts = []

        # 根据关键词判断查询方向
        if any(kw in user_input for kw in ["销量", "销售", "商品", "SKU"]):
            products = db_tool.get_product_sales(days=7)
            if products and not products[0].get("error"):
                data_parts.append(f"商品销售数据（近7天）：\n{products[:5]}")

        if any(kw in user_input for kw in ["广告", "投放", "ROI", "推广"]):
            ads = db_tool.get_ads_performance(days=7)
            if ads and not ads[0].get("error"):
                data_parts.append(f"广告投放数据（近7天）：\n{ads[:5]}")

        if any(kw in user_input for kw in ["品类", "分类", "类目"]):
            categories = db_tool.get_product_categories()
            if categories and not categories[0].get("error"):
                data_parts.append(f"品类汇总数据：\n{categories}")

        if any(kw in user_input for kw in ["渠道", "平台", "对比"]):
            platforms = db_tool.get_ads_by_platform()
            if platforms and not platforms[0].get("error"):
                data_parts.append(f"平台维度数据：\n{platforms}")

        if data_parts:
            return {"source": "database", "data": "\n\n".join(data_parts)}

        return {"source": "database", "data": "", "note": "No matching data found"}
    except Exception as e:
        logger.warning("[data_analysis] DB query failed: %s", e)
        return {"source": "database", "data": "", "error": str(e)}


def _get_basic_stats(data_str: str) -> str:
    """从数据字符串中提取数字做基础统计"""
    import re as _re
    numbers = _re.findall(r"\d+\.?\d*", data_str)
    if not numbers:
        return "No numeric data found for statistics"
    nums = [float(n) for n in numbers[:100]]  # 限制处理量
    return (
        f"数据条数: {len(nums)}, "
        f"总计: {sum(nums):.2f}, "
        f"均值: {sum(nums)/len(nums):.2f}, "
        f"最大: {max(nums):.2f}, "
        f"最小: {min(nums):.2f}"
    )


def data_analysis_skill(user_input: str) -> Dict[str, Any]:
    """数据分析技能入口"""
    try:
        llm = get_llm()

        # 1. 尝试从数据库获取数据
        db_data = _get_db_data(user_input)

        # 2. 构建分析上下文
        context_parts = [f"用户需求：{user_input}"]

        if db_data.get("data"):
            context_parts.append(f"\n【数据库数据】\n{db_data['data']}")
            stats = _get_basic_stats(db_data["data"])
            context_parts.append(f"\n【基础统计】\n{stats}")
        else:
            context_parts.append(
                "\n注意：未找到匹配的数据库数据，请基于通用知识给出分析框架和建议。"
            )

        context = "\n".join(context_parts)

        # 3. 调用 LLM 分析
        messages = [
            SystemMessage(content=DATA_ANALYSIS_SYSTEM_PROMPT),
            HumanMessage(content=context),
        ]
        response = llm.invoke(messages)
        analysis = response.content

        return {
            "type": "data_analysis",
            "data": {
                "user_input": user_input,
                "data_source": db_data.get("source", "none"),
                "has_data": bool(db_data.get("data")),
                "analysis": analysis,
            },
        }
    except Exception as e:
        logger.error("[data_analysis] error: %s", e, exc_info=True)
        return {
            "type": "data_analysis",
            "data": {
                "user_input": user_input,
                "analysis": "",
                "error": str(e),
            },
        }
