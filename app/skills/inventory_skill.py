from typing import List, Dict, Any
from app.tools.database_tool import db_tool

INVENTORY_THRESHOLDS = {
    "electronics": 50,
    "clothing": 100,
    "food": 100,
    "beauty": 200,
    "default": 100,
}


def get_threshold(category: str) -> int:
    return INVENTORY_THRESHOLDS.get(category, INVENTORY_THRESHOLDS["default"])


def get_threshold_for_category(category: str) -> int:
    return get_threshold(category)


def check_low_inventory(db_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    low_items = []
    data = db_result.get("data", [])
    for item in data:
        product_id = item.get("product_id", item.get("sku", ""))
        product_name = item.get("product_name", "")
        category = item.get("category", "default")
        stock = item.get("stock", item.get("inventory", 0))
        threshold = get_threshold(category)
        if stock < threshold:
            deficit = threshold - stock
            if stock == 0:
                urgency = "critical"
            elif stock < threshold * 0.2:
                urgency = "critical"
            elif stock < threshold * 0.5:
                urgency = "high"
            else:
                urgency = "medium"
            low_items.append(
                {
                    "product_id": product_id,
                    "product_name": product_name,
                    "category": category,
                    "current_stock": stock,
                    "threshold": threshold,
                    "deficit": deficit,
                    "urgency": urgency,
                }
            )
    return low_items


def _format_inventory_response(total_items: int, low_items: List[Dict[str, Any]]) -> str:
    urgency_labels = {"critical": "紧急", "high": "高", "medium": "中"}
    lines = [f"数据库共有 {total_items} 个商品。"]
    if not low_items:
        lines.append("所有商品库存充足，无需补货。")
        return "\n".join(lines)
    lines.append(f"其中 {len(low_items)} 个商品库存低于预警阈值：\n")
    for item in low_items:
        label = urgency_labels.get(item["urgency"], item["urgency"])
        lines.append(
            f"- **{item['product_name']}** ({item['product_id']}) | "
            f"类别: {item['category']} | "
            f"当前库存: {item['current_stock']} | "
            f"预警阈值: {item['threshold']} | "
            f"缺口: {item['deficit']} | "
            f"紧急程度: {label}"
        )
    return "\n".join(lines)


def inventory_skill(user_input: str) -> Dict[str, Any]:
    try:
        all_products = db_tool.get_all_products()
        db_result = {
            "data": [
                {
                    "product_id": p.get("sku", p.get("product_id", "")),
                    "product_name": p.get("product_name", ""),
                    "category": p.get("category", "default"),
                    "stock": p.get("inventory", 0),
                }
                for p in all_products
            ]
        }
        low_inventory_items = check_low_inventory(db_result)
        response_text = _format_inventory_response(len(all_products), low_inventory_items)
        return {
            "type": "inventory_report",
            "data": {
                "user_input": (user_input or "")[:200],
                "total_items": len(all_products),
                "low_inventory_count": len(low_inventory_items),
                "low_inventory_items": low_inventory_items,
                "thresholds": INVENTORY_THRESHOLDS,
                "response": response_text,
            },
        }
    except Exception as e:
        return {
            "type": "inventory_report",
            "data": {
                "user_input": (user_input or "")[:200],
                "total_items": 0,
                "low_inventory_count": 0,
                "low_inventory_items": [],
                "error": str(e),
                "response": f"查询库存时出错: {e}",
            },
        }


# 高风险操作标记: 涉及库存修改需要人工审批
requires_approval = True
