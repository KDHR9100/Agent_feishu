import re
from langchain_core.messages import HumanMessage, SystemMessage
from typing import Optional

import logging

from app.config import get_llm
from app.prompts import ADS_ANALYSIS_PROMPT
from app.tools.database_tool import db_tool

logger = logging.getLogger(__name__)


def extract_ad_id_from_input(user_input: str) -> Optional[str]:
    patterns = [
        r"ad_id\s*[:]?\s*(\w+)",
        r"AD\s*(\w+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, user_input, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def calculate_roi(spend: float, conversion_value: float) -> float:
    if spend == 0:
        return 0
    return round(conversion_value / spend, 2)


def calculate_ctr(clicks: int, impressions: int) -> float:
    if impressions == 0:
        return 0
    return round((clicks / impressions) * 100, 2)


def calculate_cpc(spend: float, clicks: int) -> float:
    if clicks == 0:
        return 0
    return round(spend / clicks, 2)


def compare_platforms(platform_data):
    best_roas = None
    best_platform = None
    lowest_cpc = None
    lowest_cpc_platform = None
    highest_ctr = None
    highest_ctr_platform = None

    # 兼容非 list 输入(如 DB 报错 dict), 避免崩溃
    if not isinstance(platform_data, list):
        platform_data = []

    for platform in platform_data:
        if not isinstance(platform, dict):
            continue
        # DB 聚合字段可能为 None, 统一兑底为数值, 避免比较时 TypeError
        roas = platform.get("avg_roas")
        roas = roas if isinstance(roas, (int, float)) else 0
        cpc = platform.get("avg_cpc")
        cpc = cpc if isinstance(cpc, (int, float)) else float("inf")
        ctr = platform.get("avg_ctr")
        ctr = ctr if isinstance(ctr, (int, float)) else 0

        if best_roas is None or roas > best_roas:
            best_roas = roas
            best_platform = platform.get("platform", "")

        if lowest_cpc is None or cpc < lowest_cpc:
            lowest_cpc = cpc
            lowest_cpc_platform = platform.get("platform", "")

        if highest_ctr is None or ctr > highest_ctr:
            highest_ctr = ctr
            highest_ctr_platform = platform.get("platform", "")

    return {
        "best_roas": best_roas,
        "best_roas_platform": best_platform,
        "lowest_cpc": lowest_cpc,
        "lowest_cpc_platform": lowest_cpc_platform,
        "highest_ctr": highest_ctr,
        "highest_ctr_platform": highest_ctr_platform,
    }


def _fallback_analysis(combined_data: dict) -> str:
    """LLM 不可用时，基于 DB 聚合指标生成基础分析文本（降级路径）。"""
    overall = combined_data.get("overall_metrics", {})
    lines = [
        "⚠️ AI 分析服务暂时不可用，以下为数据库聚合的原始指标：",
        "- 总花费: ¥%s" % overall.get("total_spend", 0),
        "- 总点击: %s" % overall.get("total_clicks", 0),
        "- 总转化: %s" % overall.get("total_conversions", 0),
        "- 总转化金额: ¥%s" % overall.get("total_conversion_value", 0),
        "- 整体 ROI: %s" % overall.get("overall_roi", 0),
        "- 整体 CTR: %s" % overall.get("overall_ctr", 0),
        "- 整体 CPC: ¥%s" % overall.get("overall_cpc", 0),
    ]
    pc = combined_data.get("platform_comparison", {}) or {}
    if pc.get("best_roas_platform"):
        lines.append("- 最高 ROAS 平台: %s (ROAS %s)" % (pc.get("best_roas_platform"), pc.get("best_roas")))
    if pc.get("lowest_cpc_platform"):
        lines.append("- 最低 CPC 平台: %s (CPC ¥%s)" % (pc.get("lowest_cpc_platform"), pc.get("lowest_cpc")))
    if pc.get("highest_ctr_platform"):
        lines.append("- 最高 CTR 平台: %s (CTR %s)" % (pc.get("highest_ctr_platform"), pc.get("highest_ctr")))
    return "\n".join(lines)


def ads_skill(user_input: str):
    llm = get_llm()

    extracted_ad_id = extract_ad_id_from_input(user_input)

    # 数据诚实性: 指定广告查不到时如实打标, 全店广告数据仅作参考, 防止 LLM 编造
    requested_ad_missing = False
    honesty_note = ""
    try:
        if extracted_ad_id:
            db_data = db_tool.get_ads_performance(ad_id=extracted_ad_id, days=30)
            if not db_data or (isinstance(db_data, list) and len(db_data) == 0):
                requested_ad_missing = True
                honesty_note = (
                    "用户指定的广告【%s】在数据库中没有任何投放记录。"
                    "下方 database_data 是全店其他广告的参考数据, 不是该广告的数据。" % extracted_ad_id
                )
                db_data = db_tool.get_ads_performance(days=7)
        else:
            db_data = db_tool.get_ads_performance(days=7)

        platform_data = db_tool.get_ads_by_platform()
        campaign_data = db_tool.get_campaign_performance()
    except Exception:
        db_data = []
        platform_data = []
        campaign_data = []

    ads_summary = []
    total_spend = 0
    total_clicks = 0
    total_conversions = 0
    total_conversion_value = 0

    if isinstance(db_data, list) and db_data:
        for item in db_data:
            if "error" not in item:
                spend = item.get("spend", item.get("total_spend", 0))
                clicks = item.get("clicks", item.get("total_clicks", 0))
                conversions = item.get("conversions", item.get("total_conversions", 0))
                conversion_value = item.get(
                    "conversion_value", item.get("total_conversion_value", 0)
                )
                impressions = item.get("impressions", item.get("total_impressions", 0))

                ads_summary.append(
                    {
                        "ad_id": item.get("ad_id", ""),
                        "ad_name": item.get("ad_name", ""),
                        "platform": item.get("platform", ""),
                        "clicks": clicks,
                        "impressions": impressions,
                        "spend": spend,
                        "conversions": conversions,
                        "conversion_value": conversion_value,
                        "ctr": item.get("ctr", calculate_ctr(clicks, impressions)),
                        "cpc": item.get("cpc", calculate_cpc(spend, clicks)),
                        "roas": item.get(
                            "roas", calculate_roi(spend, conversion_value)
                        ),
                        "date": item.get("date", ""),
                    }
                )
                total_spend += spend
                total_clicks += clicks
                total_conversions += conversions
                total_conversion_value += conversion_value

    overall_roi = calculate_roi(total_spend, total_conversion_value)
    overall_ctr = calculate_ctr(
        total_clicks,
        sum(
            item.get("impressions", item.get("total_impressions", 0))
            for item in ads_summary
        ),
    )
    overall_cpc = calculate_cpc(total_spend, total_clicks)

    platform_comparison = compare_platforms(platform_data)

    combined_data = {
        "database_data": ads_summary,
        "platform_data": platform_data,
        "campaign_data": campaign_data,
        "overall_metrics": {
            "total_spend": round(total_spend, 2),
            "total_clicks": total_clicks,
            "total_conversions": total_conversions,
            "total_conversion_value": round(total_conversion_value, 2),
            "overall_roi": overall_roi,
            "overall_ctr": overall_ctr,
            "overall_cpc": overall_cpc,
        },
        "platform_comparison": platform_comparison,
        "extracted_ad_id": extracted_ad_id,
        "requested_ad_missing": requested_ad_missing,
        "honesty_note": honesty_note,
        "user_input": user_input,
    }

    prompt = ADS_ANALYSIS_PROMPT.format(data=combined_data)

    messages = [
        SystemMessage(content="You are an e-commerce advertising analysis expert"),
        HumanMessage(content=prompt),
    ]

    try:
        analysis = llm.invoke(messages).content
    except Exception as exc:
        # LLM 超时/异常时降级：返回 DB 聚合原始指标，保证技能可用
        logger.warning("ads_skill LLM analysis failed, degraded to raw metrics: %s", exc)
        analysis = _fallback_analysis(combined_data)

    return {
        "type": "ads_analysis",
        "data": {
            "raw_data": combined_data,
            "analysis": analysis,
            "overall_roi": overall_roi,
            "platform_comparison": platform_comparison,
        },
    }
