import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestDatabaseTool(unittest.TestCase):
    def setUp(self):
        from app.tools.database_tool import db_tool
        self.db_tool = db_tool

    def test_get_product_sales_all(self):
        result = self.db_tool.get_product_sales()
        self.assertIsInstance(result, list)
        if result and len(result) > 0 and 'error' not in result[0]:
            self.assertIn('sku', result[0])
            self.assertIn('total_sales', result[0])
            self.assertIn('total_revenue', result[0])

    def test_get_product_sales_by_sku(self):
        result = self.db_tool.get_product_sales(sku='SKU001')
        self.assertIsInstance(result, list)

    def test_get_all_products(self):
        result = self.db_tool.get_all_products()
        self.assertIsInstance(result, list)
        if result and len(result) > 0 and 'error' not in result[0]:
            self.assertIn('sku', result[0])
            self.assertIn('product_name', result[0])

    def test_get_product_categories(self):
        result = self.db_tool.get_product_categories()
        self.assertIsInstance(result, list)

    def test_get_ads_performance_all(self):
        result = self.db_tool.get_ads_performance()
        self.assertIsInstance(result, list)
        if result and len(result) > 0 and 'error' not in result[0]:
            self.assertIn('ad_id', result[0])
            self.assertIn('total_spend', result[0])
            self.assertIn('total_conversions', result[0])

    def test_get_ads_by_platform(self):
        result = self.db_tool.get_ads_by_platform()
        self.assertIsInstance(result, list)
        if result and len(result) > 0 and 'error' not in result[0]:
            self.assertIn('platform', result[0])

    def test_query_with_params(self):
        result = self.db_tool.query(
            "SELECT COUNT(*) as count FROM product_sales"
        )
        self.assertIsInstance(result, list)


class TestProductSkill(unittest.TestCase):
    def test_extract_sku(self):
        from app.skills.product_skill import extract_sku_from_input
        
        self.assertEqual(extract_sku_from_input("SKU: SKU001"), "SKU001")
        self.assertEqual(extract_sku_from_input("SKU: ABC123"), "ABC123")
        self.assertIsNotNone(extract_sku_from_input("Product XYZ"))

    def test_analyze_sales_trend(self):
        from app.skills.product_skill import analyze_sales_trend
        
        data = [
            {'sales_volume': 100, 'revenue': 1000},
            {'sales_volume': 80, 'revenue': 800},
        ]
        result = analyze_sales_trend(data)
        self.assertEqual(result['trend'], 'rising')
        self.assertGreater(result['sales_change_pct'], 0)

    def test_calculate_profit_margin(self):
        from app.skills.product_skill import calculate_profit_margin
        
        data = [{'revenue': 1000, 'cost': 600}]
        self.assertEqual(calculate_profit_margin(data), 40.0)
        
        data = [{'revenue': 0, 'cost': 100}]
        self.assertEqual(calculate_profit_margin(data), 0)


class TestAdsSkill(unittest.TestCase):
    def test_extract_ad_id(self):
        from app.skills.ads_skill import extract_ad_id_from_input
        
        self.assertEqual(extract_ad_id_from_input("ad_id: AD001"), "AD001")
        self.assertEqual(extract_ad_id_from_input("AD ABC"), "ABC")

    def test_calculate_roi(self):
        from app.skills.ads_skill import calculate_roi
        
        self.assertEqual(calculate_roi(100, 200), 2.0)
        self.assertEqual(calculate_roi(0, 100), 0)

    def test_calculate_ctr(self):
        from app.skills.ads_skill import calculate_ctr
        
        self.assertEqual(calculate_ctr(100, 1000), 10.0)
        self.assertEqual(calculate_ctr(0, 1000), 0)

    def test_calculate_cpc(self):
        from app.skills.ads_skill import calculate_cpc
        
        self.assertEqual(calculate_cpc(100, 50), 2.0)
        self.assertEqual(calculate_cpc(100, 0), 0)


class TestContentSkill(unittest.TestCase):
    def test_detect_platform(self):
        from app.skills.content_skill import detect_platform
        
        self.assertEqual(detect_platform("Write douyin short video copy"), "douyin")
        self.assertEqual(detect_platform("Taobao detail page copy"), "taobao")
        self.assertEqual(detect_platform("Xiaohongshu notes"), "xiaohongshu")
        self.assertEqual(detect_platform("Wechat article"), "wechat")
        self.assertEqual(detect_platform("Pinduoduo promotion copy"), "pinduoduo")
        self.assertEqual(detect_platform("Write a copy"), "taobao")

    def test_detect_template(self):
        from app.skills.content_skill import detect_template
        
        self.assertEqual(detect_template("Introduce product features"), "product_introduction")
        self.assertEqual(detect_template("Promotion campaign copy"), "promotion")
        self.assertEqual(detect_template("Product review"), "review")
        self.assertEqual(detect_template("Usage tutorial"), "how_to")
        self.assertEqual(detect_template("Brand story"), "storytelling")

    def test_extract_product_info(self):
        from app.skills.content_skill import extract_product_info
        
        info = extract_product_info("Product: Wireless Headphones, Price: 199, Features: Noise cancellation")
        self.assertEqual(info.get('price'), '199')
        self.assertIn('product_name', info)
        self.assertIn('features', info)


if __name__ == '__main__':
    unittest.main()