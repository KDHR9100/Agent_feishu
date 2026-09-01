"""Listing 生成技能

用户在飞书发送 "帮我重新生成 SKU XXX 的 listing", 本技能:
1. 从用户输入提取 SKU (复用 product_skill.extract_sku_from_input)
2. 通过 database_tool 查询该 SKU 的商品信息 (product_name / category)
3. 收集商品图片 (用户输入中的路径 或 <图片根目录>/<SKU>/ 约定目录)
4. 调用 CrossLister 微服务生成合规多语言 Listing
5. 格式化为飞书友好的文本返回

图片根目录: 环境变量 PRODUCT_IMAGES_DIR, 默认 <项目根>/data/product_images
平台默认 shopee, 目标语言默认 th (TikTok Shop 泰国站场景)。
"""
import logging
import os
import re
from typing import Dict, List, Optional

from app.skills.product_skill import extract_sku_from_input
from app.tools.database_tool import db_tool
from app.tools.crosslister_client import CrossListerClient

logger = logging.getLogger("listing_skill")

# 支持的图片扩展名
_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")

# 项目根目录 (app/skills/listing_skill.py 向上三级)
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

# 默认平台与目标语言 (TikTok Shop 泰国站场景)
_DEFAULT_PLATFORM = "shopee"
_DEFAULT_TARGET_LANG = "th"


def _images_root() -> str:
    """商品图片根目录: 环境变量 PRODUCT_IMAGES_DIR 优先, 默认 data/product_images"""
    return os.environ.get(
        "PRODUCT_IMAGES_DIR", os.path.join(_PROJECT_ROOT, "data", "product_images")
    )


def extract_image_paths_from_input(user_input: str) -> List[str]:
    """从用户输入中提取真实存在的图片文件路径 (支持用户直接发图片路径)"""
    paths = []
    pattern = r"[\w/\\.~\-]+\.(?:jpg|jpeg|png|webp|gif|bmp)"
    for token in re.findall(pattern, user_input, re.IGNORECASE):
        candidate = os.path.expanduser(token)
        if os.path.isfile(candidate) and candidate not in paths:
            paths.append(candidate)
    return paths


def find_product_images(sku: str) -> List[str]:
    """按约定目录查找 SKU 商品图片: <图片根目录>/<SKU>/ 下的图片文件

    大小写两种目录名都尝试, 按文件名排序返回, 上限 20 张。
    """
    root = _images_root()
    for dirname in (sku, sku.lower()):
        sku_dir = os.path.join(root, dirname)
        if not os.path.isdir(sku_dir):
            continue
        images = sorted(
            os.path.join(sku_dir, f)
            for f in os.listdir(sku_dir)
            if f.lower().endswith(_IMAGE_EXTS)
        )
        if images:
            return images[:20]
    return []


def lookup_sku_info(sku: str) -> Optional[Dict]:
    """查询 SKU 的商品信息 (product_name / category), 查不到返回 None"""
    try:
        rows = db_tool.get_product_sales(sku=sku, days=3650)
        if rows:
            return next((r for r in rows if "error" not in r), rows[0])
        for product in db_tool.get_all_products():
            if product.get("sku") == sku:
                return product
    except Exception as e:
        logger.warning("[listing_skill] SKU 查询失败 sku=%s: %s", sku, e)
    return None


def _format_bullets(bullets) -> str:
    """将五点描述列表格式化为编号文本"""
    if isinstance(bullets, str):
        bullets = [b for b in bullets.split("\n") if b.strip()]
    if not bullets:
        return "(无)"
    return "\n".join("%d. %s" % (i, b) for i, b in enumerate(bullets, 1))


def _format_keywords(keywords) -> str:
    """后台关键词: 列表用逗号连接, 字符串原样返回"""
    if isinstance(keywords, list):
        return ", ".join(str(k) for k in keywords if k)
    return str(keywords or "(无)")


def _format_compliance(compliance: dict) -> List[str]:
    """合规审核结果格式化"""
    lines = []
    if not isinstance(compliance, dict):
        return ["合规审核: 无结果"]
    if compliance.get("passed"):
        lines.append("合规审核: ✅ 通过")
    else:
        lines.append("合规审核: ⚠️ 未通过, 请根据以下问题修改后重新生成")
    violations = compliance.get("violations") or []
    if violations:
        lines.append("违规项:")
        lines.extend("  ❌ %s" % v for v in violations)
    warnings = compliance.get("warnings") or []
    if warnings:
        lines.append("警告项:")
        lines.extend("  ⚠️ %s" % w for w in warnings)
    return lines


def format_listing(sku: str, result: dict, category: str) -> str:
    """将 CrossLister 返回结果格式化为飞书友好的文本 (标题/五点/描述分开展示)"""
    lines = [
        "✅ 已为 SKU【%s】生成多语言合规 Listing" % sku,
        "类目: %s | 平台: %s | 目标语言: %s"
        % (category, _DEFAULT_PLATFORM, _DEFAULT_TARGET_LANG),
        "",
        "【标题】",
        result.get("title") or "(无)",
    ]
    if result.get("title_zh"):
        lines.append("(中文) %s" % result["title_zh"])

    lines += ["", "【五点描述】", _format_bullets(result.get("bullet_points"))]
    bullets_zh = result.get("bullet_points_zh")
    if bullets_zh:
        lines += ["", "【五点描述(中文)】", _format_bullets(bullets_zh)]

    if result.get("description"):
        lines += ["", "【商品描述】", result["description"]]
    if result.get("description_zh"):
        lines += ["", "【商品描述(中文)】", result["description_zh"]]

    lines += ["", "【后台关键词】", _format_keywords(result.get("backend_keywords"))]

    # 视觉分析摘要: 帮助用户确认 AI 对商品图片的理解
    visual = result.get("visual_analysis")
    if isinstance(visual, dict):
        selling_points = visual.get("selling_points") or []
        detected = visual.get("detected_category") or ""
        if detected or selling_points:
            lines.append("")
            lines.append("【图片视觉分析】")
            if detected:
                lines.append("识别类目: %s" % detected)
            if selling_points:
                lines.append("识别卖点: %s" % "; ".join(selling_points[:5]))

    lines += ["", *_format_compliance(result.get("compliance") or {})]
    return "\n".join(lines)


def listing_skill(user_input: str) -> str:
    """Listing 生成技能入口

    Args:
        user_input: 用户原始输入, 如 "帮我重新生成 SKU HY00000637 的 listing"

    Returns:
        飞书友好的格式化文本; 任何异常路径都返回友好提示, 不抛异常
    """
    # ── 1. 提取 SKU ──
    sku = extract_sku_from_input(user_input)
    if not sku:
        return (
            "未能从您的消息中识别出 SKU。\n"
            "请发送类似「帮我重新生成 SKU HY00000637 的 listing」的指令。"
        )

    # ── 2. 查询 SKU 商品信息, product_name 作为类目兜底 ──
    sku_info = lookup_sku_info(sku)
    sku_missing_note = ""
    if sku_info:
        product_name = sku_info.get("product_name") or ""
        category = sku_info.get("category") or product_name or sku
    else:
        # 数据诚实性: 查不到 SKU 时如实告知, 但仍以 SKU 为类目尝试生成
        product_name = ""
        category = sku
        sku_missing_note = (
            "注意: SKU【%s】在数据库中未找到销售记录, 已按 SKU 作为类目生成, "
            "结果仅供参考。\n" % sku
        )
        logger.info("[listing_skill] SKU %s 未在数据库中找到, 继续生成", sku)

    # ── 3. 收集商品图片: 用户输入中的路径优先, 其次是约定目录 ──
    image_paths = extract_image_paths_from_input(user_input)
    if not image_paths:
        image_paths = find_product_images(sku)
    if not image_paths:
        return (
            "未找到 SKU【%s】的商品图片, 无法生成 Listing。\n"
            "您可以:\n"
            "1. 在消息中直接附上商品图片; 或\n"
            "2. 将图片放入目录: %s" % (sku, os.path.join(_images_root(), sku))
        )
    logger.info("[listing_skill] SKU=%s, 图片 %d 张, 类目=%s", sku, len(image_paths), category)

    # ── 4. 调用 CrossLister 服务 ──
    client = CrossListerClient()
    extra_info = "SKU: %s" % sku
    if product_name:
        extra_info += "; 商品名称: %s" % product_name

    result = client.generate_listing(
        image_paths=image_paths,
        category=category,
        platform=_DEFAULT_PLATFORM,
        target_lang=_DEFAULT_TARGET_LANG,
        extra_info=extra_info,
    )

    # ── 5. 错误处理: 统一转为友好提示, 不暴露 traceback ──
    if result.get("error"):
        error = result["error"]
        detail = result.get("detail", "")
        logger.error("[listing_skill] CrossLister 调用失败: %s | %s", error, detail)
        if error in ("connection_error", "timeout"):
            return (
                "Listing 服务暂时不可用, 请确认服务已启动 "
                "(当前地址: %s), 稍后重试。" % client.base_url
            )
        return "Listing 生成失败: %s\n请稍后重试, 若持续失败请联系管理员。" % (
            detail or error
        )

    # ── 6. 格式化输出 ──
    return sku_missing_note + format_listing(sku, result, category)
