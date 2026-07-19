from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from typing import Optional, List, Dict


class DatabaseTool:
    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or "sqlite:///./example.db"
        self.engine = create_engine(self.db_url)
    
    def query(self, sql: str) -> List[Dict]:
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(sql))
                columns = result.keys()
                return [dict(zip(columns, row)) for row in result.fetchall()]
        except SQLAlchemyError as e:
            return [{"error": str(e)}]
    
    def execute(self, sql: str) -> Dict:
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(sql))
                conn.commit()
                return {"affected_rows": result.rowcount}
        except SQLAlchemyError as e:
            return {"error": str(e)}
    
    def get_product_sales(self, sku: str = None, days: int = 7) -> List[Dict]:
        if sku:
            sql = f"""SELECT sku, date, sales, revenue 
                FROM product_sales 
                WHERE sku = '{sku}' 
                ORDER BY date DESC LIMIT {days}"""
        else:
            sql = f"""SELECT sku, SUM(sales) as total_sales, SUM(revenue) as total_revenue
                FROM product_sales 
                GROUP BY sku 
                ORDER BY total_sales DESC 
                LIMIT 10"""
        return self.query(sql)
    
    def get_ads_performance(self, ad_id: str = None, days: int = 7) -> List[Dict]:
        if ad_id:
            sql = f"""SELECT ad_id, date, clicks, impressions, cost, conversions
                FROM ads_performance
                WHERE ad_id = '{ad_id}'
                ORDER BY date DESC LIMIT {days}"""
        else:
            sql = f"""SELECT ad_id, SUM(clicks) as total_clicks, SUM(cost) as total_cost,
                       SUM(conversions) as total_conversions
                FROM ads_performance
                GROUP BY ad_id
                ORDER BY total_conversions DESC
                LIMIT 10"""
        return self.query(sql)


db_tool = DatabaseTool()
