import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models import init_db
from app.models.models import ProductSales, AdsPerformance, Conversation, UserProfile
from app.models.database import SessionLocal, engine
from datetime import datetime, timedelta

def seed_database():
    db = SessionLocal()
    
    try:
        if db.query(ProductSales).count() == 0:
            products = [
                ProductSales(sku="SKU001", product_name="Wireless Headphones", category="Electronics", sales_volume=1200, revenue=144000.0, cost=72000.0, inventory=500, avg_price=120.0, date=datetime.utcnow()),
                ProductSales(sku="SKU002", product_name="Smart Watch", category="Electronics", sales_volume=850, revenue=170000.0, cost=85000.0, inventory=300, avg_price=200.0, date=datetime.utcnow()),
                ProductSales(sku="SKU003", product_name="Leather Wallet", category="Accessories", sales_volume=2500, revenue=50000.0, cost=15000.0, inventory=1000, avg_price=20.0, date=datetime.utcnow()),
                ProductSales(sku="SKU004", product_name="Cotton T-Shirt", category="Clothing", sales_volume=5000, revenue=75000.0, cost=25000.0, inventory=2000, avg_price=15.0, date=datetime.utcnow()),
                ProductSales(sku="SKU005", product_name="Stainless Steel Water Bottle", category="Home Goods", sales_volume=1800, revenue=54000.0, cost=18000.0, inventory=600, avg_price=30.0, date=datetime.utcnow()),
            ]
            db.add_all(products)
            db.commit()
            print("Seeded 5 product sales records")
        
        if db.query(AdsPerformance).count() == 0:
            ads = [
                AdsPerformance(ad_id="AD001", ad_name="Wireless Headphones Campaign", platform="Feishu", clicks=2500, impressions=50000, spend=5000.0, conversions=120, conversion_value=14400.0, ctr=5.0, cpc=2.0, roas=2.88, date=datetime.utcnow()),
                AdsPerformance(ad_id="AD002", ad_name="Smart Watch Promotion", platform="WeChat", clicks=1800, impressions=30000, spend=3600.0, conversions=85, conversion_value=17000.0, ctr=6.0, cpc=2.0, roas=4.72, date=datetime.utcnow()),
                AdsPerformance(ad_id="AD003", ad_name="Electronics Bundle", platform="Douyin", clicks=4200, impressions=80000, spend=8400.0, conversions=200, conversion_value=35000.0, ctr=5.25, cpc=2.0, roas=4.17, date=datetime.utcnow()),
            ]
            db.add_all(ads)
            db.commit()
            print("Seeded 3 ads performance records")
        
        if db.query(UserProfile).count() == 0:
            users = [
                UserProfile(user_id="ou_admin", user_name="Admin", department="Tech", role="admin", preferences={"language": "zh", "theme": "dark"}, interaction_count=0),
                UserProfile(user_id="ou_manager", user_name="Manager", department="Operations", role="manager", preferences={"language": "zh"}, interaction_count=0),
            ]
            db.add_all(users)
            db.commit()
            print("Seeded 2 user profiles")
            
    except Exception as e:
        db.rollback()
        print(f"Error seeding database: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    print("Creating database tables...")
    init_db()
    print("Database tables created successfully")
    
    print("\nSeeding initial data...")
    seed_database()
    print("\nDatabase initialization complete!")