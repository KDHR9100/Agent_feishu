import os
import sys
import csv
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime

from app.models import init_db
from app.models.models import UserProfile
from app.models.database import SessionLocal

# CSV 数据文件目录
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

PRODUCT_SALES_FIELDS = [
    "sku", "product_name", "category", "sales_volume", "revenue", "cost",
    "inventory", "avg_price", "date",
]

ADS_PERFORMANCE_FIELDS = [
    "ad_id", "ad_name", "platform", "clicks", "impressions", "spend",
    "conversions", "conversion_value", "ctr", "cpc", "roas",
    "campaign_id", "ad_group_id", "date",
]


def _write_csv_file(name, fieldnames, rows):
    path = os.path.join(DATA_DIR, name)
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  -> wrote {len(rows)} rows to {path}")


def seed_csv_data():
    """将业务种子数据写入 CSV 文件。"""
    products_path = os.path.join(DATA_DIR, "product_sales.csv")
    if not os.path.exists(products_path):
        today = datetime.utcnow().strftime("%Y-%m-%d")
        products = [
            {"sku": "SKU001", "product_name": "Wireless Headphones", "category": "Electronics", "sales_volume": 1200, "revenue": 144000.0, "cost": 72000.0, "inventory": 500, "avg_price": 120.0, "date": today},
            {"sku": "SKU002", "product_name": "Smart Watch", "category": "Electronics", "sales_volume": 850, "revenue": 170000.0, "cost": 85000.0, "inventory": 300, "avg_price": 200.0, "date": today},
            {"sku": "SKU003", "product_name": "Leather Wallet", "category": "Accessories", "sales_volume": 2500, "revenue": 50000.0, "cost": 15000.0, "inventory": 1000, "avg_price": 20.0, "date": today},
            {"sku": "SKU004", "product_name": "Cotton T-Shirt", "category": "Clothing", "sales_volume": 5000, "revenue": 75000.0, "cost": 25000.0, "inventory": 2000, "avg_price": 15.0, "date": today},
            {"sku": "SKU005", "product_name": "Stainless Steel Water Bottle", "category": "Home Goods", "sales_volume": 1800, "revenue": 54000.0, "cost": 18000.0, "inventory": 600, "avg_price": 30.0, "date": today},
        ]
        _write_csv_file("product_sales.csv", PRODUCT_SALES_FIELDS, products)
        print("Seeded 5 product sales records (CSV)")
    else:
        print("product_sales.csv already exists, skipping")

    ads_path = os.path.join(DATA_DIR, "ads_performance.csv")
    if not os.path.exists(ads_path):
        today = datetime.utcnow().strftime("%Y-%m-%d")
        ads = [
            {"ad_id": "AD001", "ad_name": "Wireless Headphones Campaign", "platform": "Feishu", "clicks": 2500, "impressions": 50000, "spend": 5000.0, "conversions": 120, "conversion_value": 14400.0, "ctr": 5.0, "cpc": 2.0, "roas": 2.88, "campaign_id": "", "ad_group_id": "", "date": today},
            {"ad_id": "AD002", "ad_name": "Smart Watch Promotion", "platform": "WeChat", "clicks": 1800, "impressions": 30000, "spend": 3600.0, "conversions": 85, "conversion_value": 17000.0, "ctr": 6.0, "cpc": 2.0, "roas": 4.72, "campaign_id": "", "ad_group_id": "", "date": today},
            {"ad_id": "AD003", "ad_name": "Electronics Bundle", "platform": "Douyin", "clicks": 4200, "impressions": 80000, "spend": 8400.0, "conversions": 200, "conversion_value": 35000.0, "ctr": 5.25, "cpc": 2.0, "roas": 4.17, "campaign_id": "", "ad_group_id": "", "date": today},
        ]
        _write_csv_file("ads_performance.csv", ADS_PERFORMANCE_FIELDS, ads)
        print("Seeded 3 ads performance records (CSV)")
    else:
        print("ads_performance.csv already exists, skipping")


def seed_database():
    """将用户画像等系统数据写入 SQLite (ORM 表)。"""
    db = SessionLocal()
    try:
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
    print("Creating system database tables...")
    init_db()
    print("System tables created successfully")

    print("\nSeeding business data (CSV)...")
    seed_csv_data()

    print("\nSeeding system data (SQLite)...")
    seed_database()

    print("\nInitialization complete!")
