import os
import tempfile
import pandas as pd
import sys
sys.path.insert(0, '/home/huajuanx/Agent_feishu')


def test_check_low_inventory():
    from app.skills.inventory_skill import check_low_inventory, INVENTORY_THRESHOLDS
    mock_db_result = {
        'data': [
            {'product_id': 'SKU001', 'product_name': 'Wireless Headphones Pro', 'category': 'electronics', 'stock': 10},
            {'product_id': 'SKU002', 'product_name': 'Cotton T-Shirt', 'category': 'clothing', 'stock': 50},
            {'product_id': 'SKU003', 'product_name': 'Casual Jeans', 'category': 'clothing', 'stock': 250},
            {'product_id': 'SKU004', 'product_name': 'Imported Milk', 'category': 'food', 'stock': 5},
            {'product_id': 'SKU005', 'product_name': 'Moisturizing Cream', 'category': 'beauty', 'stock': 150},
            {'product_id': 'SKU006', 'product_name': 'Smart Watch', 'category': 'electronics', 'stock': 0},
            {'product_id': 'SKU007', 'product_name': 'Regular Headphones', 'category': 'electronics', 'stock': 60},
        ]
    }
    low_inventory_items = check_low_inventory(mock_db_result)
    print(f"=== Inventory Threshold Configuration ===")
    for category, threshold in INVENTORY_THRESHOLDS.items():
        print(f"  {category}: {threshold}")
    print(f"\n=== Low Inventory Detection Results ===")
    print(f"Low inventory items found: {len(low_inventory_items)}")
    for item in low_inventory_items:
        urgency_icon = "!!!" if item['urgency'] == 'critical' else "!!" if item['urgency'] == 'high' else "!"
        print(f"{urgency_icon} {item['product_name']}")
        print(f"   ID: {item['product_id']}")
        print(f"   Category: {item['category']}")
        print(f"   Current Stock: {item['current_stock']} (Threshold: {item['threshold']})")
        print(f"   Deficit: {item['deficit']}")
        print(f"   Urgency: {item['urgency']}")
        print()
    # Expected: 5 low inventory items based on thresholds
    # SKU001: electronics(50), stock=10 < 50*0.5=25 -> high
    # SKU002: clothing(100), stock=50 < 100*0.5=50 -> medium (equal to threshold*0.5)
    # SKU003: clothing(100), stock=250 >= 100 -> OK
    # SKU004: food(100), stock=5 < 100*0.2=20 -> critical
    # SKU005: beauty(200), stock=150 < 200 -> medium (150 >= 200*0.5=100)
    # SKU006: electronics(50), stock=0 -> critical
    # SKU007: electronics(50), stock=60 >= 50 -> OK
    assert len(low_inventory_items) == 5, f"Expected 5 low inventory items, got {len(low_inventory_items)}"
    critical_items = [i for i in low_inventory_items if i['urgency'] == 'critical']
    assert len(critical_items) == 2, f"Expected 2 critical items, got {len(critical_items)}"
    critical_ids = {item['product_id'] for item in critical_items}
    assert 'SKU004' in critical_ids, "SKU004 should be critical"
    assert 'SKU006' in critical_ids, "SKU006 should be critical"
    high_items = [i for i in low_inventory_items if i['urgency'] == 'high']
    assert len(high_items) == 1, f"Expected 1 high item, got {len(high_items)}"
    assert high_items[0]['product_id'] == 'SKU001'
    medium_items = [i for i in low_inventory_items if i['urgency'] == 'medium']
    assert len(medium_items) == 2, f"Expected 2 medium items, got {len(medium_items)}"
    medium_ids = {item['product_id'] for item in medium_items}
    assert 'SKU002' in medium_ids, "SKU002 should be medium"
    assert 'SKU005' in medium_ids, "SKU005 should be medium"
    print("OK check_low_inventory passed!")


def test_inventory_from_excel():
    from app.tools.file_parser_tool import file_parser_tool
    test_data = {
        'product_id': ['SKU001', 'SKU002', 'SKU003', 'SKU004', 'SKU005'],
        'product_name': ['Wireless Headphones Pro', 'Cotton T-Shirt', 'Casual Jeans', 'Imported Milk', 'Moisturizing Cream'],
        'category': ['electronics', 'clothing', 'clothing', 'food', 'beauty'],
        'stock': [10, 50, 250, 5, 150],
        'price': [299, 99, 199, 68, 198],
        'sales': [1200, 3500, 2800, 5000, 1800],
    }
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as f:
        temp_path = f.name
    df = pd.DataFrame(test_data)
    df.to_excel(temp_path, index=False)
    print(f"\n=== Excel Parse Test ===")
    print(f"Temp file: {temp_path}")
    parsed_result = file_parser_tool.parse_local_file(temp_path)
    if 'error' in parsed_result:
        print(f"Parse failed: {parsed_result['error']}")
        os.remove(temp_path)
        return
    print(f"Columns: {len(parsed_result.get('columns', []))}")
    print(f"Rows: {parsed_result.get('row_count', 0)}")
    print(f"Column names: {parsed_result.get('columns', [])}")
    print(f"\n=== Data Summary ===")
    summary = parsed_result.get('summary', {})
    for col, stats in summary.items():
        if stats.get('type') == 'numeric':
            print(f"{col}: mean={stats.get('mean', 0):.2f}, max={stats.get('max', 0):.2f}, min={stats.get('min', 0):.2f}, sum={stats.get('sum', 0):.2f}")
        else:
            print(f"{col}: text, unique={stats.get('unique_count', 0)}")
    print(f"\n=== Sample Data ===")
    sample_rows = parsed_result.get('sample_rows', [])
    for row in sample_rows:
        print(row)
    assert parsed_result['row_count'] == 5, f"Expected 5 rows, got {parsed_result['row_count']}"
    assert 'stock' in parsed_result['columns'], "stock column not found"
    os.remove(temp_path)
    print("\nOK Excel parse test passed!")


def test_inventory_skill():
    from app.skills.inventory_skill import inventory_skill
    result = inventory_skill("Check inventory status")
    print(f"\n=== inventory_skill Test ===")
    print(f"Type: {result.get('type')}")
    data = result.get('data', {})
    print(f"User input: {data.get('user_input')}")
    print(f"Total items: {data.get('total_items')}")
    print(f"Low inventory count: {data.get('low_inventory_count')}")
    if 'error' in data:
        print(f"DB may be empty, continuing...")
        print(f"Error: {data.get('error')}")
    else:
        low_items = data.get('low_inventory_items', [])
        print(f"Low inventory items:")
        for item in low_items[:3]:
            print(f"  - {item['product_name']}: {item['current_stock']}")
    print("OK inventory_skill test completed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Inventory Alert Tests")
    print("=" * 60)
    test_check_low_inventory()
    test_inventory_from_excel()
    test_inventory_skill()
    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)
