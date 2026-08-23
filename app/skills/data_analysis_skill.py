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
import datetime
from typing import Any, Dict
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_llm, logger
from app.utils.time_utils import parse_time_range

DATA_ANALYSIS_SYSTEM_PROMPT = """你是一个专业的电商数据分析师。
请基于提供的数据，进行深入分析并生成专业报告。

## 数据诚实性铁律（最高优先级，违反即无效）
1. 严禁编造：你输出的每一个数字、SKU、日期都必须能在提供的数据中找到出处；数据里没有的内容一律不许写。
2. 若未提供有效数据：只能说明"暂无相关数据"并给出分析思路框架，绝不能虚构任何具体数字、销量、ROI。

分析要求：
1. 数据概览：关键指标汇总
2. 趋势分析：同比/环比变化
3. 异常检测：识别数据中的异常波动
4. 归因分析：分析变化背后的可能原因
5. 行动建议：给出可执行的优化方案

请使用中文输出，包含具体数据支撑。"""


def _filter_by_date(rows, start_date, end_date):
    """按日期范围过滤数据行"""
    start_str = start_date.isoformat()
    end_str = end_date.isoformat()
    return [r for r in rows if start_str <= str(r.get("date", "")) <= end_str]


def _get_db_data(user_input: str) -> Dict[str, Any]:
    """尝试从数据库获取相关数据，根据用户输入解析时间范围"""
    try:
        from app.tools.database_tool import db_tool

        start_date, end_date, time_desc = parse_time_range(user_input)
        data_parts = []

        # 根据关键词判断查询方向
        if any(kw in user_input for kw in ["销量", "销售", "商品", "SKU"]):
            all_products = db_tool.read_data("product_sales.csv")
            products = _filter_by_date(all_products, start_date, end_date)
            if products:
                data_parts.append(f"商品销售数据（{time_desc}）：\n{products[:10]}")

        if any(kw in user_input for kw in ["广告", "投放", "ROI", "推广"]):
            all_ads = db_tool.read_data("ads_performance.csv")
            ads = _filter_by_date(all_ads, start_date, end_date)
            if ads:
                data_parts.append(f"广告投放数据（{time_desc}）：\n{ads[:10]}")

        if any(kw in user_input for kw in ["品类", "分类", "类目"]):
            all_products = db_tool.read_data("product_sales.csv")
            products = _filter_by_date(all_products, start_date, end_date)
            if products:
                # 按品类汇总
                from collections import defaultdict
                groups = defaultdict(lambda: {"sales_volume": 0, "revenue": 0.0})
                for r in products:
                    cat = r.get("category", "")
                    groups[cat]["sales_volume"] += r.get("sales_volume", 0) or 0
                    groups[cat]["revenue"] += r.get("revenue", 0) or 0
                categories = [{"category": k, **v} for k, v in groups.items()]
                categories.sort(key=lambda x: x["revenue"], reverse=True)
                data_parts.append(f"品类汇总数据（{time_desc}）：\n{categories}")

        if any(kw in user_input for kw in ["渠道", "平台", "对比"]):
            all_ads = db_tool.read_data("ads_performance.csv")
            ads = _filter_by_date(all_ads, start_date, end_date)
            if ads:
                from collections import defaultdict
                groups = defaultdict(lambda: {"clicks": 0, "spend": 0.0, "conversions": 0})
                for r in ads:
                    plat = r.get("platform", "")
                    groups[plat]["clicks"] += r.get("clicks", 0) or 0
                    groups[plat]["spend"] += r.get("spend", 0) or 0
                    groups[plat]["conversions"] += r.get("conversions", 0) or 0
                platforms = [{"platform": k, **v} for k, v in groups.items()]
                platforms.sort(key=lambda x: x["spend"], reverse=True)
                data_parts.append(f"平台维度数据（{time_desc}）：\n{platforms}")

        if data_parts:
            return {"source": "database", "data": "\n\n".join(data_parts), "time_desc": time_desc}

        return {"source": "database", "data": "", "time_desc": time_desc, "note": "No matching data found"}
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
        time_desc = db_data.get("time_desc", "近7天")
        context_parts = [
            f"用户需求：{user_input}",
            f"数据时间范围：{time_desc}，当前日期：{datetime.date.today()}",
        ]

        if db_data.get("data"):
            context_parts.append(f"\n【数据库数据】\n{db_data['data']}")
            stats = _get_basic_stats(db_data["data"])
            context_parts.append(f"\n【基础统计】\n{stats}")
        else:
            context_parts.append(
                f"\n注意：{time_desc}未找到匹配的数据库数据。请如实说明暂无相关数据，"
                "可给出分析思路框架，但严禁编造任何具体数字。"
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
