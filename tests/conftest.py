import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Create test DB tables and seed data before any tests run."""
    from app.config import config
    from sqlalchemy import create_engine, text

    engine = create_engine(
        config.DATABASE_URL,
        connect_args={"check_same_thread": False},
    )

    with engine.connect() as conn:
        # Create product_sales table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS product_sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sku TEXT,
                product_name TEXT,
                category TEXT,
                sales_volume INTEGER DEFAULT 0,
                revenue REAL DEFAULT 0,
                cost REAL DEFAULT 0,
                inventory INTEGER DEFAULT 0,
                avg_price REAL DEFAULT 0,
                date TEXT
            )
        """))

        # Create ads_performance table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ads_performance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ad_id TEXT,
                ad_name TEXT,
                platform TEXT,
                clicks INTEGER DEFAULT 0,
                impressions INTEGER DEFAULT 0,
                spend REAL DEFAULT 0,
                conversions INTEGER DEFAULT 0,
                conversion_value REAL DEFAULT 0,
                ctr REAL DEFAULT 0,
                cpc REAL DEFAULT 0,
                roas REAL DEFAULT 0,
                campaign_id TEXT,
                ad_group_id TEXT,
                date TEXT
            )
        """))

        # Seed sample data
        conn.execute(text("""
            INSERT INTO product_sales
            (sku, product_name, category, sales_volume, revenue, cost,
             inventory, avg_price, date)
            VALUES
                ('SKU001', 'test_product_a', 'cat_a', 100, 9900.0,
                 4000.0, 50, 99.0, '2026-07-25'),
                ('SKU002', 'test_product_b', 'cat_b', 200, 5800.0,
                 2000.0, 120, 29.0, '2026-07-25')
        """))

        conn.execute(text("""
            INSERT INTO ads_performance
            (ad_id, ad_name, platform, clicks, impressions, spend,
             conversions, conversion_value, ctr, cpc, roas,
             campaign_id, date)
            VALUES
                ('AD001', 'test_ad_a', 'taobao', 500, 10000, 1000.0,
                 50, 4950.0, 5.0, 2.0, 4.95, 'CAMP001', '2026-07-25'),
                ('AD002', 'test_ad_b', 'douyin', 300, 8000, 600.0,
                 30, 870.0, 3.75, 2.0, 1.45, 'CAMP001', '2026-07-25')
        """))

        conn.commit()

    yield engine
    engine.dispose()


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def file_tool(tmp_dir):
    from app.tools.file_tool import FileTool
    return FileTool(base_dir=tmp_dir)
