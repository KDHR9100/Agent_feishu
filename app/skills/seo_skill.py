import re
from typing import Any, Dict
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_llm, logger


class SeoSkill:
    def __init__(self):
        self.supported_platforms = ["taobao", "tmall", "jd", "douyin"]

    def extract_seo_info(self, user_input: str) -> Dict[str, str]:
        keyword_match = re.search(r"关键词[:\s]*([^\s]+)", user_input)
        product_match = re.search(r"(宝贝|商品|产品)[:\s]*([^\s]+)", user_input)
        platform_match = re.search(
            r"(taobao|tmall|jd|douyin|淘宝|天猫|京东|抖音)", user_input, re.IGNORECASE
        )

        platform_map = {
            "淘宝": "taobao",
            "天猫": "tmall",
            "京东": "jd",
            "抖音": "douyin",
        }

        platform = platform_match.group(1) if platform_match else ""
        platform = platform_map.get(
            platform, platform.lower() if platform else "taobao"
        )

        return {
            "keyword": keyword_match.group(1) if keyword_match else "",
            "product": product_match.group(2) if product_match else "",
            "platform": platform,
        }

    def analyze_seo(self, user_input: str) -> Dict[str, Any]:
        llm = get_llm()
        seo_info = self.extract_seo_info(user_input)

        keyword_data = self._get_keyword_data(seo_info)

        if "error" in keyword_data:
            fallback_prompt = f"""
You are an e-commerce SEO optimization expert.

The user wants SEO analysis for:
- Keyword: {seo_info['keyword']}
- Product: {seo_info['product']}
- Platform: {seo_info['platform']}

The keyword analysis API is currently unavailable.

Please provide general SEO optimization guidance for {seo_info['platform']}:
1. Keyword research methods
2. Title optimization strategies
3. Description writing tips
4. Content optimization best practices
5. Ranking factors on {seo_info['platform']}
6. Recommendations based on user request: {user_input}
"""
            messages = [
                SystemMessage(content="You are an expert e-commerce SEO specialist"),
                HumanMessage(content=fallback_prompt),
            ]
            analysis = llm.invoke(messages).content

            return {
                "type": "seo_analysis",
                "data": {
                    "user_input": user_input,
                    "seo_info": seo_info,
                    "analysis": analysis,
                    "note": "Using fallback analysis (keyword API unavailable)",
                },
            }

        prompt = f"""
You are an e-commerce SEO optimization expert.

[KEYWORD DATA]
{keyword_data}

[USER REQUEST]
{user_input}

Please provide SEO analysis and optimization recommendations:
1. Keyword difficulty assessment
2. Search volume analysis
3. Recommended keywords (long-tail, related)
4. Title and description optimization suggestions
5. Content strategy recommendations
6. Competitor keyword analysis
"""

        messages = [
            SystemMessage(content="You are an expert e-commerce SEO specialist"),
            HumanMessage(content=prompt),
        ]

        analysis = llm.invoke(messages).content

        return {
            "type": "seo_analysis",
            "data": {
                "user_input": user_input,
                "seo_info": seo_info,
                "keyword_data": keyword_data,
                "analysis": analysis,
            },
        }

    def _get_keyword_data(self, seo_info: Dict[str, str]) -> Dict[str, Any]:
        try:
            from app.tools.keyword_tool import keyword_tool

            if seo_info["keyword"]:
                return keyword_tool.analyze_keyword(seo_info["keyword"])
            else:
                return keyword_tool.get_hot_keywords(seo_info["platform"])

        except ImportError:
            return {"error": "Keyword tool not available"}
        except Exception as e:
            logger.error(f"[SeoSkill] Keyword API error: {e}")
            return {"error": f"Keyword API failed: {str(e)}"}


def seo_skill(user_input: str) -> Dict[str, Any]:
    skill = SeoSkill()
    return skill.analyze_seo(user_input)
