import os
import sys
import csv
import tempfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 测试环境禁用路由结果缓存: 保证各用例的 LLM 调用行为可被 mock 精确断言
os.environ["ROUTER_CACHE_ENABLED"] = "false"
# 测试环境禁用回滚记录持久化: 防止跨运行恢复的待确认动作被 sweep 回滚,
# 污染共享 Mock store 状态 (持久化路径由独立验证脚本覆盖)
os.environ["ROLLBACK_PERSISTENCE_ENABLED"] = "false"


def _create_test_csvs(data_dir: str):
    """在指定目录创建测试用的 CSV 数据文件。"""
    products = [
        {"sku": "SKU001", "product_name": "test_product_a", "category": "cat_a",
         "sales_volume": "100", "revenue": "9900.0", "cost": "4000.0",
         "inventory": "50", "avg_price": "99.0", "date": "2026-07-25"},
        {"sku": "SKU002", "product_name": "test_product_b", "category": "cat_b",
         "sales_volume": "200", "revenue": "5800.0", "cost": "2000.0",
         "inventory": "120", "avg_price": "29.0", "date": "2026-07-25"},
    ]
    with open(os.path.join(data_dir, "product_sales.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(products[0].keys()))
        w.writeheader()
        w.writerows(products)

    ads = [
        {"ad_id": "AD001", "ad_name": "test_ad_a", "platform": "taobao",
         "clicks": "500", "impressions": "10000", "spend": "1000.0",
         "conversions": "50", "conversion_value": "4950.0",
         "ctr": "5.0", "cpc": "2.0", "roas": "4.95",
         "campaign_id": "CAMP001", "ad_group_id": "", "date": "2026-07-25"},
        {"ad_id": "AD002", "ad_name": "test_ad_b", "platform": "douyin",
         "clicks": "300", "impressions": "8000", "spend": "600.0",
         "conversions": "30", "conversion_value": "870.0",
         "ctr": "3.75", "cpc": "2.0", "roas": "1.45",
         "campaign_id": "CAMP001", "ad_group_id": "", "date": "2026-07-25"},
    ]
    with open(os.path.join(data_dir, "ads_performance.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(ads[0].keys()))
        w.writeheader()
        w.writerows(ads)


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Create test CSV data files and system DB tables before any tests run."""
    from app.config import config
    from sqlalchemy import create_engine, text

    # 创建临时目录存放测试 CSV
    tmp_data_dir = tempfile.mkdtemp(prefix="test_biz_data_")
    _create_test_csvs(tmp_data_dir)
    os.environ["BIZ_DATA_DIR"] = tmp_data_dir

    # 系统表仍需 SQLite (conversations, token_usage_logs 等 ORM 模型)
    engine = create_engine(
        config.DATABASE_URL,
        connect_args={"check_same_thread": False},
    )

    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS product_sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sku TEXT, product_name TEXT, category TEXT,
                sales_volume INTEGER DEFAULT 0, revenue REAL DEFAULT 0,
                cost REAL DEFAULT 0, inventory INTEGER DEFAULT 0,
                avg_price REAL DEFAULT 0, date TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ads_performance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ad_id TEXT, ad_name TEXT, platform TEXT,
                clicks INTEGER DEFAULT 0, impressions INTEGER DEFAULT 0,
                spend REAL DEFAULT 0, conversions INTEGER DEFAULT 0,
                conversion_value REAL DEFAULT 0, ctr REAL DEFAULT 0,
                cpc REAL DEFAULT 0, roas REAL DEFAULT 0,
                campaign_id TEXT, ad_group_id TEXT, date TEXT
            )
        """))
        conn.commit()

    yield engine

    engine.dispose()
    os.environ.pop("BIZ_DATA_DIR", None)


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def file_tool(tmp_dir):
    from app.tools.file_tool import FileTool
    return FileTool(base_dir=tmp_dir)
