import sys
import os
sys.path.insert(0, '/home/huajuanx/Agent_feishu')

import unittest
from unittest.mock import patch, MagicMock
from typing import Dict, Any


class TestSkillIntegration(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault('OPENAI_API_KEY', 'test_key')
        os.environ.setdefault('OPENAI_API_BASE', 'https://api.openai.com/v1')
        os.environ.setdefault('OPENAI_MODEL_NAME', 'gpt-4o')

    def test_product_skill(self):
        from app.skills.product_skill import product_skill
        
        result = product_skill("分析商品SKU001的销售情况")
        
        self.assertIsInstance(result, dict)
        self.assertIn('type', result)
        self.assertIn('data', result)
        
        data = result['data']
        self.assertIsInstance(data, dict)
        
        print(f"✓ product_skill: type={result['type']}")

    def test_ads_skill(self):
        from app.skills.ads_skill import ads_skill
        
        result = ads_skill("分析广告投放效果")
        
        self.assertIsInstance(result, dict)
        self.assertIn('type', result)
        self.assertIn('data', result)
        
        print(f"✓ ads_skill: type={result['type']}")

    def test_content_skill(self):
        from app.skills.content_skill import content_skill
        
        result = content_skill("写一段无线耳机的商品描述")
        
        self.assertIsInstance(result, dict)
        self.assertIn('type', result)
        self.assertIn('data', result)
        
        data = result['data']
        self.assertIsInstance(data, dict)
        self.assertIn('copy', data)
        
        print(f"✓ content_skill: type={result['type']}, copy_length={len(data.get('copy', ''))}")

    def test_help_skill(self):
        from app.skills.help_skill import help_skill
        
        result = help_skill("帮助")
        
        self.assertIsInstance(result, dict)
        self.assertIn('type', result)
        self.assertIn('data', result)
        
        print(f"✓ help_skill: type={result['type']}")

    def test_data_analysis_skill(self):
        from app.skills.data_analysis_skill import data_analysis_skill
        
        result = data_analysis_skill("分析这个表格")
        
        self.assertIsInstance(result, dict)
        self.assertIn('type', result)
        self.assertIn('data', result)
        
        print(f"✓ data_analysis_skill: type={result['type']}")

    def test_inventory_skill(self):
        from app.skills.inventory_skill import inventory_skill
        
        result = inventory_skill("查询库存状态")
        
        self.assertIsInstance(result, dict)
        self.assertIn('type', result)
        self.assertIn('data', result)
        
        data = result['data']
        self.assertIsInstance(data, dict)
        self.assertIn('low_inventory_count', data)
        
        print(f"✓ inventory_skill: type={result['type']}, low_inventory={data['low_inventory_count']}")

    def test_competitor_skill(self):
        from app.skills.competitor_skill import competitor_skill
        
        result = competitor_skill("分析淘宝上无线耳机的竞品")
        
        self.assertIsInstance(result, dict)
        self.assertIn('type', result)
        self.assertIn('data', result)
        
        data = result['data']
        self.assertIsInstance(data, dict)
        self.assertIn('analysis', data)
        
        print(f"✓ competitor_skill: type={result['type']}")

    def test_seo_skill(self):
        from app.skills.seo_skill import seo_skill
        
        result = seo_skill("优化无线耳机的SEO关键词")
        
        self.assertIsInstance(result, dict)
        self.assertIn('type', result)
        self.assertIn('data', result)
        
        data = result['data']
        self.assertIsInstance(data, dict)
        self.assertIn('analysis', data)
        
        print(f"✓ seo_skill: type={result['type']}")

    def test_support_skill(self):
        from app.skills.support_skill import support_skill
        
        result = support_skill("我的订单怎么还没发货？订单号ORD001")
        
        self.assertIsInstance(result, dict)
        self.assertIn('type', result)
        self.assertIn('data', result)
        
        data = result['data']
        self.assertIsInstance(data, dict)
        self.assertIn('response', data)
        self.assertIn('intent', data)
        
        print(f"✓ support_skill: type={result['type']}, intent={data['intent']}")


class TestToolIntegration(unittest.TestCase):
    def test_file_parser_tool_csv(self):
        from app.tools.file_parser_tool import file_parser_tool
        import tempfile
        import csv
        
        with tempfile.NamedTemporaryFile(suffix='.csv', mode='w', delete=False) as f:
            writer = csv.writer(f)
            writer.writerow(['product', 'price', 'sales'])
            writer.writerow(['A', 100, 50])
            writer.writerow(['B', 200, 30])
            temp_path = f.name
        
        try:
            result = file_parser_tool.parse_local_file(temp_path)
            
            self.assertIsInstance(result, dict)
            self.assertNotIn('error', result)
            self.assertEqual(result['row_count'], 2)
            self.assertEqual(len(result['columns']), 3)
            
            print(f"✓ file_parser_tool CSV: rows={result['row_count']}, cols={len(result['columns'])}")
        finally:
            os.remove(temp_path)

    def test_file_parser_tool_excel(self):
        from app.tools.file_parser_tool import file_parser_tool
        import tempfile
        import pandas as pd
        
        df = pd.DataFrame({'product': ['A', 'B'], 'price': [100, 200], 'sales': [50, 30]})
        
        with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as f:
            temp_path = f.name
        
        df.to_excel(temp_path, index=False)
        
        try:
            result = file_parser_tool.parse_local_file(temp_path)
            
            self.assertIsInstance(result, dict)
            self.assertNotIn('error', result)
            self.assertEqual(result['row_count'], 2)
            
            print(f"✓ file_parser_tool Excel: rows={result['row_count']}")
        finally:
            os.remove(temp_path)

    def test_file_parser_tool_pdf(self):
        from app.tools.file_parser_tool import file_parser_tool
        import tempfile
        from PyPDF2 import PdfWriter
        
        writer = PdfWriter()
        page = writer.add_blank_page(width=612, height=792)
        
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
            temp_path = f.name
        
        with open(temp_path, 'wb') as f:
            writer.write(f)
        
        try:
            result = file_parser_tool.parse_local_file(temp_path)
            
            self.assertIsInstance(result, dict)
            self.assertEqual(result['type'], 'pdf_text')
            
            print(f"✓ file_parser_tool PDF: type={result['type']}")
        finally:
            os.remove(temp_path)

    def test_file_parser_tool_word(self):
        from app.tools.file_parser_tool import file_parser_tool
        import tempfile
        from docx import Document
        
        doc = Document()
        doc.add_paragraph("Test document")
        
        with tempfile.NamedTemporaryFile(suffix='.docx', delete=False) as f:
            temp_path = f.name
        
        doc.save(temp_path)
        
        try:
            result = file_parser_tool.parse_local_file(temp_path)
            
            self.assertIsInstance(result, dict)
            self.assertEqual(result['type'], 'word_text')
            
            print(f"✓ file_parser_tool Word: type={result['type']}")
        finally:
            os.remove(temp_path)

    def test_database_tool(self):
        from app.tools.database_tool import database_tool
        
        result = database_tool.get_inventory_data()
        
        self.assertIsInstance(result, dict)
        self.assertIn('data', result)
        
        print(f"✓ database_tool: items={len(result.get('data', []))}")

    def test_feishu_tool(self):
        from app.tools.feishu_tool import feishu_tool
        
        token = feishu_tool.get_access_token()
        
        self.assertIsInstance(token, str)
        
        print(f"✓ feishu_tool: access_token_length={len(token) if token else 0}")


class TestErrorHandling(unittest.TestCase):
    def test_inventory_threshold_config(self):
        from app.skills.inventory_skill import INVENTORY_THRESHOLDS, get_threshold_for_category
        
        self.assertIn('default', INVENTORY_THRESHOLDS)
        self.assertIn('electronics', INVENTORY_THRESHOLDS)
        
        self.assertEqual(get_threshold_for_category('electronics'), 50)
        self.assertEqual(get_threshold_for_category('unknown'), 100)
        
        print("✓ inventory_threshold_config: OK")

    def test_check_low_inventory_empty(self):
        from app.skills.inventory_skill import check_low_inventory
        
        result = check_low_inventory({'data': []})
        
        self.assertEqual(result, [])
        
        print("✓ check_low_inventory_empty: OK")

    def test_check_low_inventory_error(self):
        from app.skills.inventory_skill import check_low_inventory
        
        result = check_low_inventory({'error': 'database error'})
        
        self.assertEqual(result, [])
        
        print("✓ check_low_inventory_error: OK")

    def test_inventory_monitor(self):
        from app.tasks.inventory_monitor import inventory_monitor
        
        self.assertIsNotNone(inventory_monitor)
        
        print("✓ inventory_monitor: OK")


if __name__ == '__main__':
    print("=" * 70)
    print("COMPREHENSIVE INTEGRATION TESTS")
    print("=" * 70)
    
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestSkillIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestToolIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestErrorHandling))
    
    runner = unittest.TextTestRunner(verbosity=0)
    result = runner.run(suite)
    
    print("\n" + "=" * 70)
    print(f"RESULTS: {result.testsRun} tests run")
    print(f"SUCCESS: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"FAILURES: {len(result.failures)}")
    print(f"ERRORS: {len(result.errors)}")
    
    if result.failures:
        print("\nFAILURES:")
        for test, traceback in result.failures:
            print(f"  - {test}")
    
    if result.errors:
        print("\nERRORS:")
        for test, traceback in result.errors:
            print(f"  - {test}")
    
    print("\n" + "=" * 70)
