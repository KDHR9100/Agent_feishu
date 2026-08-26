import re
from langchain_core.messages import HumanMessage, SystemMessage
from typing import Optional

from app.config import get_llm
from app.prompts import PRODUCT_ANALYSIS_PROMPT
from app.tools.database_tool import db_tool


def extract_sku_from_input(user_input: str) -> Optional[str]:
    # 捕获完整 SKU 词元 (含 "SKU" 前缀), 如 SKU001 / SKU-A001 / SKU-XXXX
    patterns = [
        r"(SKU[-_]?[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*)",
    ]
    for pattern in patterns:
        match = re.search(pattern, user_input, re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return None


def analyze_sales_trend(data):
    if len(data) < 2:
        return {
            "trend": "insufficient",
            "message": "Not enough data for trend analysis",
        }
    recent = data[-1]
    previous = data[0]
    sales_diff = recent.get("sales_volume", 0) - previous.get("sales_volume", 0)
    revenue_diff = recent.get("revenue", 0) - previous.get("revenue", 0)
    sales_pct = (
        (sales_diff / previous.get("sales_volume", 1)) * 100
        if previous.get("sales_volume", 0) > 0
        else 0
    )
    revenue_pct = (
        (revenue_diff / previous.get("revenue", 1)) * 100
        if previous.get("revenue", 0) > 0
        else 0
    )

    if sales_pct > 0:
        trend = "rising"
    elif sales_pct < 0:
        trend = "falling"
    else:
        trend = "stable"

    return {
        "trend": trend,
        "sales_change_pct": round(sales_pct, 2),
        "revenue_change_pct": round(revenue_pct, 2),
        "recent_sales": recent.get("sales_volume", 0),
        "previous_sales": previous.get("sales_volume", 0),
    }


def calculate_profit_margin(data):
    total_revenue = sum(item.get("revenue", 0) for item in data)
    total_cost = sum(item.get("cost", 0) for item in data)
    if total_revenue == 0:
        return 0
    return round(((total_revenue - total_cost) / total_revenue) * 100, 2)


def product_skill(user_input: str):
    llm = get_llm()

    extracted_sku = extract_sku_from_input(user_input)

    # 数据诚实性: 指定 SKU 查不到时如实打标, 全店数据仅作参考, 防止 LLM 编造
    requested_sku_missing = False
    honesty_note = ""
    try:
        if extracted_sku:
            db_data = db_tool.get_product_sales(sku=extracted_sku, days=180)
            if not db_data or (isinstance(db_data, list) and len(db_data) == 0):
                requested_sku_missing = True
                honesty_note = (
                    "用户指定的 SKU【%s】在数据库中没有任何销售记录。"
                    "下方 database_data 是全店其他商品的参考数据, 不是该 SKU 的数据。" % extracted_sku
                )
                db_data = db_tool.get_product_sales(days=180)
        else:
            db_data = db_tool.get_product_sales(days=180)

        all_products = db_tool.get_all_products()
        categories = db_tool.get_product_categories()
    except Exception:
        db_data = []
        all_products = []
        categories = []

    sales_summary = []
    if isinstance(db_data, list) and db_data:
        for item in db_data:
            if "error" not in item:
                sales_summary.append(
                    {
                        "sku": item.get("sku", ""),
                        "product_name": item.get("product_name", ""),
                        "category": item.get("category", ""),
                        "sales_volume": item.get(
                            "sales_volume", item.get("total_sales", 0)
                        ),
                        "revenue": item.get("revenue", item.get("total_revenue", 0)),
                        "cost": item.get("cost", item.get("total_cost", 0)),
                        "inventory": item.get(
                            "inventory", item.get("total_inventory", 0)
                        ),
                        "avg_price": item.get("avg_price", 0),
                        "date": item.get("date", ""),
                    }
                )

    trend_analysis = {}
    if len(sales_summary) >= 2:
        trend_analysis = analyze_sales_trend(sales_summary)

    profit_margin = calculate_profit_margin(sales_summary)

    combined_data = {
        "database_data": sales_summary,
        "all_products": all_products,
        "categories": categories,
        "trend_analysis": trend_analysis,
        "profit_margin": profit_margin,
        "extracted_sku": extracted_sku,
        "requested_sku_missing": requested_sku_missing,
        "honesty_note": honesty_note,
        "user_input": user_input,
    }

    prompt = PRODUCT_ANALYSIS_PROMPT.format(data=combined_data)

    messages = [
        SystemMessage(content="You are an e-commerce product analysis expert"),
        HumanMessage(content=prompt),
    ]

    analysis = llm.invoke(messages).content

    return {
        "type": "product_analysis",
        "data": {
            "raw_data": combined_data,
            "analysis": analysis,
            "trend": trend_analysis.get("trend"),
            "profit_margin": profit_margin,
        },
    }
