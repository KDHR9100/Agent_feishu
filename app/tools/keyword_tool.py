"""关键词分析工具 - 为 SEO 技能提供关键词数据支持

提供三种数据来源（按优先级）：
1. 数据库查询：从本地 product_sales 表提取已有商品的关键词
2. 内置热词库：预置各平台电商高频关键词
3. LLM 生成：基于用户输入让 LLM 推荐关键词

使用方式：
    from app.tools.keyword_tool import keyword_tool
    result = keyword_tool.analyze_keyword("连衣裙")
    hot = keyword_tool.get_hot_keywords("taobao")
"""
import logging
from typing import Dict, List, Any

logger = logging.getLogger("keyword_tool")

# 内置各平台电商高频关键词库
PLATFORM_HOT_KEYWORDS = {
    "taobao": [
        "连衣裙", "T恤", "牛仔裤", "运动鞋", "手机壳",
        "充电宝", "零食", "面膜", "防晒霜", "收纳盒",
        "无线耳机", "夏季新款", "显瘦", "百搭", "爆款",
    ],
    "tmall": [
        "品牌女装", "正品保障", "旗舰店", "高端定制",
        "轻奢", "设计师款", "大牌平替", "礼盒装",
    ],
    "jd": [
        "数码", "家电", "3C配件", "自营", "次日达",
        "品质保障", "官方授权", "智能设备", "办公用品",
    ],
    "douyin": [
        "同款", "网红推荐", "直播间", "限时秒杀",
        "好物分享", "测评", "种草", "必买清单",
    ],
}

# 关键词 SEO 评分规则（模拟数据）
KEYWORD_DIFFICULTY = {
    "连衣裙": {"search_volume": 85000, "difficulty": "high", "cpc": 2.5},
    "T恤": {"search_volume": 120000, "difficulty": "high", "cpc": 1.8},
    "手机壳": {"search_volume": 95000, "difficulty": "medium", "cpc": 1.2},
    "充电宝": {"search_volume": 60000, "difficulty": "high", "cpc": 3.0},
    "面膜": {"search_volume": 78000, "difficulty": "high", "cpc": 2.8},
    "防晒霜": {"search_volume": 65000, "difficulty": "medium", "cpc": 2.2},
    "运动鞋": {"search_volume": 72000, "difficulty": "high", "cpc": 2.0},
    "无线耳机": {"search_volume": 55000, "difficulty": "medium", "cpc": 3.5},
    "收纳盒": {"search_volume": 42000, "difficulty": "low", "cpc": 0.8},
    "零食": {"search_volume": 88000, "difficulty": "high", "cpc": 1.5},
}


class KeywordTool:
    """关键词分析工具"""

    def analyze_keyword(self, keyword: str) -> Dict[str, Any]:
        """分析指定关键词的 SEO 数据

        Args:
            keyword: 目标关键词

        Returns:
            包含搜索量、竞争度、CPC、推荐长尾词等数据
        """
        # 1. 查内置评分库
        base_data = KEYWORD_DIFFICULTY.get(keyword, None)

        # 2. 尝试从数据库查询相关商品数据
        db_data = self._query_db_keywords(keyword)

        # 3. 生成长尾词推荐
        long_tail = self._generate_long_tail(keyword)

        result = {
            "keyword": keyword,
            "search_volume": base_data["search_volume"] if base_data else "N/A",
            "difficulty": base_data["difficulty"] if base_data else "unknown",
            "cpc": base_data["cpc"] if base_data else "N/A",
            "long_tail_keywords": long_tail,
            "related_products": db_data,
        }
        logger.info(
            "[keyword_tool] analyzed keyword=%s, volume=%s, difficulty=%s",
            keyword,
            result["search_volume"],
            result["difficulty"],
        )
        return result

    def get_hot_keywords(self, platform: str = "taobao") -> Dict[str, Any]:
        """获取指定平台的热门关键词

        Args:
            platform: 平台名称 (taobao/tmall/jd/douyin)

        Returns:
            包含平台热门关键词列表
        """
        keywords = PLATFORM_HOT_KEYWORDS.get(
            platform, PLATFORM_HOT_KEYWORDS["taobao"]
        )
        logger.info(
            "[keyword_tool] hot keywords for %s: %d items",
            platform,
            len(keywords),
        )
        return {
            "platform": platform,
            "hot_keywords": keywords,
            "count": len(keywords),
        }

    def _query_db_keywords(self, keyword: str) -> List[Dict[str, Any]]:
        """从数据库查询包含该关键词的商品"""
        try:
            from app.tools.database_tool import db_tool
            products = db_tool.get_all_products()
            related = []
            for p in products:
                name = p.get("product_name", "")
                if keyword in name or name in keyword:
                    related.append({
                        "sku": p.get("sku", ""),
                        "product_name": name,
                        "category": p.get("category", ""),
                    })
            return related[:5]  # 最多返回5个
        except Exception as e:
            logger.warning("[keyword_tool] DB query failed: %s", e)
            return []

    def _generate_long_tail(self, keyword: str) -> List[str]:
        """基于关键词生成长尾词推荐"""
        # 常见的长尾词后缀模式
        suffixes = [
            f"{keyword} 新款",
            f"{keyword} 热销",
            f"{keyword} 包邮",
            f"{keyword} 推荐",
            f"{keyword} 排行",
            f"{keyword} 品牌",
            f"买{keyword}",
            f"{keyword} 测评",
            f"高性价{keyword}",
            f"{keyword} 选购指南",
        ]
        return suffixes


keyword_tool = KeywordTool()
