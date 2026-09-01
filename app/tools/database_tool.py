import csv
import logging
import os
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from collections import defaultdict

# 项目根目录下的 data/ 作为演示数据目录
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_DEFAULT_DATA_DIR = os.path.join(_PROJECT_ROOT, "data")

logger = logging.getLogger("database_tool")

# data_real 存在与否的探测结果缓存 (避免每次读数据都探测/刷日志)
_detected_dir: Optional[str] = None


def _resolve_data_dir() -> str:
    """数据目录解析优先级:
    1. 环境变量 BIZ_DATA_DIR (显式指定, 永远最高优先级)
    2. 本地存在 data_real/ 目录 -> 自动使用真实业务数据
       (data_real 已加入 .gitignore, 他人 clone 仓库时不存在, 自动回退演示数据)
    3. data/ 演示数据
    """
    global _detected_dir
    env_dir = os.environ.get("BIZ_DATA_DIR")
    if env_dir:
        return env_dir
    if _detected_dir is None:
        real_dir = os.path.join(_PROJECT_ROOT, "data_real")
        if os.path.isdir(real_dir):
            _detected_dir = real_dir
            logger.info("[db] 检测到 data_real/, 自动使用真实业务数据")
        else:
            _detected_dir = _DEFAULT_DATA_DIR
            logger.info("[db] 未检测到 data_real/, 使用演示数据")
    return _detected_dir


def _cast_row(row: Dict[str, str]) -> Dict[str, Any]:
    """将 CSV 字符串值转换为合适的 Python 类型。"""
    casted = {}
    for k, v in row.items():
        if v == "" or v is None:
            casted[k] = None
            continue
        # 尝试 int
        try:
            casted[k] = int(v)
            continue
        except ValueError:
            pass
        # 尝试 float
        try:
            casted[k] = float(v)
            continue
        except ValueError:
            pass
        casted[k] = v
    return casted


class DatabaseTool:
    """业务数据读写工具，数据源为 CSV 文件。"""

    def __init__(self, data_dir: Optional[str] = None):
        self._fixed_data_dir = data_dir

    @property
    def _data_dir(self) -> str:
        return self._fixed_data_dir or _resolve_data_dir()

    def _read(self, name: str) -> List[Dict[str, Any]]:
        path = os.path.join(self._data_dir, name)
        if not os.path.exists(path):
            return []
        rows = []
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(_cast_row(row))
        return rows

    def read_data(self, name: str) -> List[Dict[str, Any]]:
        """读取指定 CSV 数据文件的全部内容，返回解析后的行列表。"""
        return self._read(name)

    def _write(self, name: str, rows: List[Dict[str, Any]], fieldnames: List[str]):
        path = os.path.join(self._data_dir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    # ── product_sales ──────────────────────────────────────────────

    def get_product_sales(
        self, sku: Optional[str] = None, days: int = 7
    ) -> List[Dict[str, Any]]:
        rows = self._read("product_sales.csv")
        date_threshold = (datetime.utcnow() - timedelta(days=days)).isoformat()

        if sku:
            return [
                r for r in rows
                if r.get("sku") == sku and str(r.get("date", "")) >= date_threshold
            ]
        else:
            # 按 SKU 聚合
            groups = defaultdict(lambda: {
                "sales_volume": 0, "revenue": 0.0, "cost": 0.0,
                "inventory": 0, "avg_price_sum": 0.0, "count": 0,
            })
            for r in rows:
                key = (r.get("sku", ""), r.get("product_name", ""), r.get("category", ""))
                g = groups[key]
                g["sales_volume"] += r.get("sales_volume", 0) or 0
                g["revenue"] += r.get("revenue", 0) or 0
                g["cost"] += r.get("cost", 0) or 0
                g["inventory"] += r.get("inventory", 0) or 0
                g["avg_price_sum"] += r.get("avg_price", 0) or 0
                g["count"] += 1

            result = []
            for (sku_val, name, cat), g in groups.items():
                result.append({
                    "sku": sku_val,
                    "product_name": name,
                    "category": cat,
                    "total_sales": g["sales_volume"],
                    "total_revenue": g["revenue"],
                    "total_cost": g["cost"],
                    "total_inventory": g["inventory"],
                    "avg_price": g["avg_price_sum"] / g["count"] if g["count"] else 0,
                })
            result.sort(key=lambda x: x["total_sales"], reverse=True)
            return result[:10]

    def get_product_by_sku(self, sku: str) -> Dict[str, Any]:
        rows = self._read("product_sales.csv")
        for r in rows:
            if r.get("sku") == sku:
                return r
        return {}

    def get_all_products(self) -> List[Dict[str, Any]]:
        """返回每个 SKU 最新日期的记录，按 product_name 排序。"""
        rows = self._read("product_sales.csv")
        # 按 SKU 取最新日期
        latest = {}
        for r in rows:
            sku_val = r.get("sku", "")
            date_val = str(r.get("date", ""))
            if sku_val not in latest or date_val > str(latest[sku_val].get("date", "")):
                latest[sku_val] = r
        result = list(latest.values())
        result.sort(key=lambda x: x.get("product_name", ""))
        return result

    def get_product_categories(self) -> List[Dict[str, Any]]:
        rows = self._read("product_sales.csv")
        groups = defaultdict(lambda: {"sales_volume": 0, "revenue": 0.0})
        for r in rows:
            cat = r.get("category", "")
            groups[cat]["sales_volume"] += r.get("sales_volume", 0) or 0
            groups[cat]["revenue"] += r.get("revenue", 0) or 0
        result = []
        for cat, g in groups.items():
            result.append({
                "category": cat,
                "total_sales": g["sales_volume"],
                "total_revenue": g["revenue"],
            })
        result.sort(key=lambda x: x["total_revenue"], reverse=True)
        return result

    # ── ads_performance ────────────────────────────────────────────

    def get_ads_performance(
        self, ad_id: Optional[str] = None, days: int = 7
    ) -> List[Dict[str, Any]]:
        rows = self._read("ads_performance.csv")
        date_threshold = (datetime.utcnow() - timedelta(days=days)).isoformat()

        if ad_id:
            return [
                r for r in rows
                if r.get("ad_id") == ad_id and str(r.get("date", "")) >= date_threshold
            ]
        else:
            groups = defaultdict(lambda: {
                "clicks": 0, "impressions": 0, "spend": 0.0,
                "conversions": 0, "conversion_value": 0.0,
                "ctr_sum": 0.0, "cpc_sum": 0.0, "roas_sum": 0.0, "count": 0,
            })
            for r in rows:
                key = (r.get("ad_id", ""), r.get("ad_name", ""), r.get("platform", ""))
                g = groups[key]
                g["clicks"] += r.get("clicks", 0) or 0
                g["impressions"] += r.get("impressions", 0) or 0
                g["spend"] += r.get("spend", 0) or 0
                g["conversions"] += r.get("conversions", 0) or 0
                g["conversion_value"] += r.get("conversion_value", 0) or 0
                g["ctr_sum"] += r.get("ctr", 0) or 0
                g["cpc_sum"] += r.get("cpc", 0) or 0
                g["roas_sum"] += r.get("roas", 0) or 0
                g["count"] += 1

            result = []
            for (aid, aname, plat), g in groups.items():
                result.append({
                    "ad_id": aid,
                    "ad_name": aname,
                    "platform": plat,
                    "total_clicks": g["clicks"],
                    "total_impressions": g["impressions"],
                    "total_spend": g["spend"],
                    "total_conversions": g["conversions"],
                    "total_conversion_value": g["conversion_value"],
                    "avg_ctr": g["ctr_sum"] / g["count"] if g["count"] else 0,
                    "avg_cpc": g["cpc_sum"] / g["count"] if g["count"] else 0,
                    "avg_roas": g["roas_sum"] / g["count"] if g["count"] else 0,
                })
            result.sort(key=lambda x: x["total_conversions"], reverse=True)
            return result[:10]

    def get_ads_by_platform(self) -> List[Dict[str, Any]]:
        rows = self._read("ads_performance.csv")
        groups = defaultdict(lambda: {
            "clicks": 0, "impressions": 0, "spend": 0.0,
            "conversions": 0, "conversion_value": 0.0,
            "roas_sum": 0.0, "ctr_sum": 0.0, "cpc_sum": 0.0, "count": 0,
        })
        for r in rows:
            plat = r.get("platform", "")
            g = groups[plat]
            g["clicks"] += r.get("clicks", 0) or 0
            g["impressions"] += r.get("impressions", 0) or 0
            g["spend"] += r.get("spend", 0) or 0
            g["conversions"] += r.get("conversions", 0) or 0
            g["conversion_value"] += r.get("conversion_value", 0) or 0
            g["roas_sum"] += r.get("roas", 0) or 0
            g["ctr_sum"] += r.get("ctr", 0) or 0
            g["cpc_sum"] += r.get("cpc", 0) or 0
            g["count"] += 1

        result = []
        for plat, g in groups.items():
            result.append({
                "platform": plat,
                "total_clicks": g["clicks"],
                "total_impressions": g["impressions"],
                "total_spend": g["spend"],
                "total_conversions": g["conversions"],
                "total_conversion_value": g["conversion_value"],
                "avg_roas": g["roas_sum"] / g["count"] if g["count"] else 0,
                "avg_ctr": g["ctr_sum"] / g["count"] if g["count"] else 0,
                "avg_cpc": g["cpc_sum"] / g["count"] if g["count"] else 0,
            })
        result.sort(key=lambda x: x["total_spend"], reverse=True)
        return result

    def get_campaign_performance(
        self, campaign_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        rows = self._read("ads_performance.csv")
        if campaign_id:
            filtered = [r for r in rows if r.get("campaign_id") == campaign_id]
        else:
            filtered = [r for r in rows if r.get("campaign_id")]

        groups = defaultdict(lambda: {
            "clicks": 0, "spend": 0.0, "conversions": 0,
            "conversion_value": 0.0, "roas_sum": 0.0, "count": 0,
        })
        for r in filtered:
            key = (r.get("campaign_id", ""), r.get("ad_group_id", ""))
            g = groups[key]
            g["clicks"] += r.get("clicks", 0) or 0
            g["spend"] += r.get("spend", 0) or 0
            g["conversions"] += r.get("conversions", 0) or 0
            g["conversion_value"] += r.get("conversion_value", 0) or 0
            g["roas_sum"] += r.get("roas", 0) or 0
            g["count"] += 1

        result = []
        for (cid, gid), g in groups.items():
            result.append({
                "campaign_id": cid,
                "ad_group_id": gid,
                "total_clicks": g["clicks"],
                "total_spend": g["spend"],
                "total_conversions": g["conversions"],
                "total_conversion_value": g["conversion_value"],
                "avg_roas": g["roas_sum"] / g["count"] if g["count"] else 0,
            })
        result.sort(key=lambda x: x["total_spend"], reverse=True)
        return result


db_tool = DatabaseTool()
database_tool = db_tool
