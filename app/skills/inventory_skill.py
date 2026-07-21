from typing import List, Dict, Any
from app.tools.database_tool import db_tool

INVENTORY_THRESHOLDS = {
    'electronics': 50,
    'clothing': 100,
    'food': 100,
    'beauty': 200,
    'default': 100,
}

def get_threshold(category: str) -> int:
    return INVENTORY_THRESHOLDS.get(category, INVENTORY_THRESHOLDS['default'])

def check_low_inventory(db_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    low_items = []
    data = db_result.get('data', [])
    for item in data:
        product_id = item.get('product_id', item.get('sku', ''))
        product_name = item.get('product_name', '')
        category = item.get('category', 'default')
        stock = item.get('stock', item.get('inventory', 0))
        threshold = get_threshold(category)
        if stock < threshold:
            deficit = threshold - stock
            if stock == 0:
                urgency = 'critical'
            elif stock < threshold * 0.2:
                urgency = 'critical'
            elif stock < threshold * 0.5:
                urgency = 'high'
            else:
                urgency = 'medium'
            low_items.append({
                'product_id': product_id,
                'product_name': product_name,
                'category': category,
                'current_stock': stock,
                'threshold': threshold,
                'deficit': deficit,
                'urgency': urgency,
            })
    return low_items

def inventory_skill(user_input: str) -> Dict[str, Any]:
    try:
        all_products = db_tool.get_all_products()
        db_result = {
            'data': [
                {
                    'product_id': p.get('sku', p.get('product_id', '')),
                    'product_name': p.get('product_name', ''),
                    'category': p.get('category', 'default'),
                    'stock': p.get('inventory', 0),
                }
                for p in all_products
            ]
        }
        low_inventory_items = check_low_inventory(db_result)
        return {
            'type': 'inventory_report',
            'data': {
                'user_input': user_input,
                'total_items': len(all_products),
                'low_inventory_count': len(low_inventory_items),
                'low_inventory_items': low_inventory_items,
                'thresholds': INVENTORY_THRESHOLDS,
            }
        }
    except Exception as e:
        return {
            'type': 'inventory_report',
            'data': {
                'user_input': user_input,
                'total_items': 0,
                'low_inventory_count': 0,
                'low_inventory_items': [],
                'error': str(e),
            }
        }
