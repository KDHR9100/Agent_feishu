from typing import List, Dict, Any
import re

from app.tools.database_tool import db_tool

INVENTORY_THRESHOLDS = {
    "electronics": 50,
    "clothing": 100,
    "food": 100,
    "beauty": 200,
    "default": 100,
}

# M17c: 用户指定 SKU 时必须定向回答该 SKU, 而非返回全店低库存清单
_SKU_RE = re.compile(r"SKU[\s\-_]?[A-Za-z0-9\-_]+", re.IGNORECASE)


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


def _extract_target_sku(user_input: str):
    """从输入中提取显式 SKU (归一为大写无空格), 未提及时返回 None"""
    if not user_input:
        return None
    m = _SKU_RE.search(user_input)
    return m.group(0).upper().replace(" ", "") if m else None


def _sku_matches(row_sku: str, target: str) -> bool:
    """SKU 匹配: 兼容 'SKU-A001' 与 'A001' 两种写法 (归一化后比对)"""
    if not row_sku:
        return False
    a = str(row_sku).strip().upper()
    b = target.upper()
    a_bare = re.sub(r"^SKU[\s\-_]*", "", a)
    b_bare = re.sub(r"^SKU[\s\-_]*", "", b)
    return a == b or a_bare == b_bare


def _format_sku_response(row: Dict[str, Any]) -> str:
    """指定 SKU 的定向库存答复 (确定性文案, 含补货判断)"""
    sku = row.get("sku", row.get("product_id", ""))
    name = row.get("product_name", "")
    category = row.get("category", "default") or "default"
    stock = row.get("inventory", 0)
    try:
        stock = int(stock)
    except (TypeError, ValueError):
        stock = 0
    threshold = get_threshold(category)
    lines = [
        "📦 商品库存查询结果",
        "- 商品: %s（%s）" % (name or "未命名商品", sku),
        "- 类别: %s" % category,
        "- 当前库存: %d 件" % stock,
        "- 预警阈值: %d 件" % threshold,
    ]
    if stock <= 0:
        lines.append("- ⛔ 库存为 0，属于缺货状态，请立即安排补货！")
    elif stock < threshold:
        lines.append(
            "- ⚠️ 低于预警阈值，缺口 %d 件，紧急程度: %s"
            % (threshold - stock, "critical" if stock < threshold * 0.2 else "high")
        )
    else:
        lines.append("- ✅ 库存充足，高于预警阈值 %d 件" % (stock - threshold))
    return "\n".join(lines)


def inventory_skill(user_input: str) -> Dict[str, Any]:
    try:
        all_products = db_tool.get_all_products()
        # M17c: 用户指定 SKU 时定向回答该 SKU (查无此 SKU 时如实说明, 不拿
        # 全店清单冒充答案)
        target_sku = _extract_target_sku(user_input)
        if target_sku:
            matched = None
            for p in all_products:
                if _sku_matches(p.get("sku", p.get("product_id", "")), target_sku):
                    matched = p
                    break
            if matched is None:
                return {
                    "type": "inventory_report",
                    "data": {
                        "user_input": (user_input or "")[:200],
                        "total_items": len(all_products),
                        "low_inventory_count": 0,
                        "low_inventory_items": [],
                        "response": (
                            "❌ 数据库中未找到商品 %s（当前库内共 %d 个商品）。\n"
                            "请确认 SKU 编号是否正确；也可以先让我列出全部商品。"
                            % (target_sku, len(all_products))
                        ),
                    },
                }
            row = {
                "sku": matched.get("sku", matched.get("product_id", "")),
                "product_name": matched.get("product_name", ""),
                "category": matched.get("category", "default"),
                "inventory": matched.get("inventory", 0),
            }
            return {
                "type": "inventory_report",
                "data": {
                    "user_input": (user_input or "")[:200],
                    "total_items": len(all_products),
                    "low_inventory_count": 0,
                    "low_inventory_items": [],
                    "target_sku": target_sku,
                    "response": _format_sku_response(row),
                },
            }
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
