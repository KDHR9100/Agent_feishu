from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

from app.config import config


class DatabaseTool:
    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or config.DATABASE_URL
        self.engine = create_engine(
            self.db_url, connect_args={"check_same_thread": False}
        )

    def query(
        self, sql: str, params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(sql), params or {})
                columns = result.keys()
                return [dict(zip(columns, row)) for row in result.fetchall()]
        except SQLAlchemyError as e:
            return [{"error": str(e)}]

    def execute(
        self, sql: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(sql), params or {})
                conn.commit()
                return {"affected_rows": result.rowcount}
        except SQLAlchemyError as e:
            return {"error": str(e)}

    def get_product_sales(
        self, sku: Optional[str] = None, days: int = 7
    ) -> List[Dict[str, Any]]:
        if sku:
            date_threshold = (datetime.utcnow() - timedelta(days=days)).isoformat()
            sql = """SELECT sku, product_name, category, sales_volume, revenue, cost, inventory, avg_price, date
                     FROM product_sales
                     WHERE sku = :sku AND date >= :date_threshold
                     ORDER BY date DESC"""
            return self.query(sql, {"sku": sku, "date_threshold": date_threshold})
        else:
            sql = """SELECT sku, product_name, category, SUM(sales_volume) as total_sales,
                       SUM(revenue) as total_revenue, SUM(cost) as total_cost,
                       SUM(inventory) as total_inventory, AVG(avg_price) as avg_price
                     FROM product_sales
                     GROUP BY sku, product_name, category
                     ORDER BY total_sales DESC
                     LIMIT 10"""
            return self.query(sql)

    def get_product_by_sku(self, sku: str) -> Dict[str, Any]:
        sql = """SELECT * FROM product_sales WHERE sku = :sku LIMIT 1"""
        result = self.query(sql, {"sku": sku})
        return result[0] if result else {}

    def get_all_products(self) -> List[Dict[str, Any]]:
        sql = """SELECT DISTINCT sku, product_name, category FROM product_sales ORDER BY product_name"""
        return self.query(sql)

    def get_product_categories(self) -> List[Dict[str, Any]]:
        sql = """SELECT category, SUM(sales_volume) as total_sales, SUM(revenue) as total_revenue
                 FROM product_sales
                 GROUP BY category
                 ORDER BY total_revenue DESC"""
        return self.query(sql)

    def get_ads_performance(
        self, ad_id: Optional[str] = None, days: int = 7
    ) -> List[Dict[str, Any]]:
        if ad_id:
            date_threshold = (datetime.utcnow() - timedelta(days=days)).isoformat()
            sql = """SELECT ad_id, ad_name, platform, clicks, impressions, spend, conversions,
                       conversion_value, ctr, cpc, roas, date
                     FROM ads_performance
                     WHERE ad_id = :ad_id AND date >= :date_threshold
                     ORDER BY date DESC"""
            return self.query(sql, {"ad_id": ad_id, "date_threshold": date_threshold})
        else:
            sql = """SELECT ad_id, ad_name, platform, SUM(clicks) as total_clicks,
                       SUM(impressions) as total_impressions, SUM(spend) as total_spend,
                       SUM(conversions) as total_conversions, SUM(conversion_value) as total_conversion_value,
                       AVG(ctr) as avg_ctr, AVG(cpc) as avg_cpc, AVG(roas) as avg_roas
                     FROM ads_performance
                     GROUP BY ad_id, ad_name, platform
                     ORDER BY total_conversions DESC
                     LIMIT 10"""
            return self.query(sql)

    def get_ads_by_platform(self) -> List[Dict[str, Any]]:
        sql = """SELECT platform, SUM(clicks) as total_clicks, SUM(impressions) as total_impressions,
                   SUM(spend) as total_spend, SUM(conversions) as total_conversions,
                   SUM(conversion_value) as total_conversion_value,
                   AVG(roas) as avg_roas, AVG(ctr) as avg_ctr, AVG(cpc) as avg_cpc
                 FROM ads_performance
                 GROUP BY platform
                 ORDER BY total_spend DESC"""
        return self.query(sql)

    def get_campaign_performance(
        self, campaign_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        if campaign_id:
            sql = """SELECT campaign_id, ad_group_id, SUM(clicks) as total_clicks,
                       SUM(spend) as total_spend, SUM(conversions) as total_conversions,
                       SUM(conversion_value) as total_conversion_value, AVG(roas) as avg_roas
                     FROM ads_performance
                     WHERE campaign_id = :campaign_id
                     GROUP BY campaign_id, ad_group_id
                     ORDER BY total_conversions DESC"""
            return self.query(sql, {"campaign_id": campaign_id})
        else:
            sql = """SELECT campaign_id, SUM(clicks) as total_clicks, SUM(spend) as total_spend,
                       SUM(conversions) as total_conversions, SUM(conversion_value) as total_conversion_value,
                       AVG(roas) as avg_roas
                     FROM ads_performance
                     WHERE campaign_id IS NOT NULL
                     GROUP BY campaign_id
                     ORDER BY total_spend DESC"""
            return self.query(sql)


db_tool = DatabaseTool()
database_tool = db_tool
