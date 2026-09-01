# -*- coding: utf-8 -*-
"""真实业务数据导入脚本

从 data/raw/ 下的 TikTok Shop 导出 Excel 生成脱敏聚合数据:
- data_real/ads_performance.csv   广告投放数据(创意级 + 店铺计划级, USD)
- data_real/product_sales.csv     商品销售数据(订单按 SKU+日期聚合, THB)

数据来源与口径:
- 创意级数据: 视频素材粒度的曝光/点击/转化/成本/收入 (2026-04-13 ~ 04-19 窗口)
- 店铺计划级: Product campaign 日报(按日)与周期汇总(记为区间末日), 无曝光/点击字段
- 订单: 按 (Seller SKU, 下单日期) 聚合, 剔除已取消订单;
        cost 为每单出库成本(来自订单文件附带的 SKU 成本小表)
- 脱敏: 丢弃责任人/买家信息/订单号/物流单号, 店铺保留账号代号(本土18/跨境32等)

产出文件仅供本地使用(已被 .gitignore 排除), 运行时通过
BIZ_DATA_DIR=data_real 让应用读取真实数据。

用法:
    python3 scripts/import_real_data.py
"""
import csv
import os
import re
import sys
from datetime import datetime

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE_DIR, "data", "raw")
OUT_DIR = os.path.join(BASE_DIR, "data_real")

ADS_HEADER = [
    "ad_id", "ad_name", "platform", "clicks", "impressions", "spend",
    "conversions", "conversion_value", "ctr", "cpc", "roas",
    "campaign_id", "ad_group_id", "date",
]
PRODUCT_HEADER = [
    "sku", "product_name", "category", "sales_volume", "revenue",
    "cost", "inventory", "avg_price", "date",
]


def _num(v, default=0.0):
    """安全转 float"""
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _int(v, default=0):
    return int(_num(v, default))


def _clean_text(v, max_len=80):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).replace("\n", " ").strip()[:max_len]


# ── 1. 店铺广告计划数据 (Product campaign data) ──────────────────────

CAMPAIGN_FILE_RE = re.compile(
    r"^(?P<acct>\d+)?Product campaign data "
    r"(?P<start>\d{4}-\d{2}-\d{2}) - (?P<end>\d{4}-\d{2}-\d{2})\.xlsx$"
)


def parse_campaign_files():
    """解析店铺计划级广告文件, 返回 {(ad_id, date): row}"""
    rows = {}
    # 特殊命名文件: 张轩瑜 本土20 Glow Up Thai 4.27-5.3 五折户 → 本土20
    special = "张轩瑜 本土20 Glow Up Thai 4.27-5.3 五折户.xlsx"
    acct_inherit = {}  # ad_id → account, 用于给未知账号文件补账号

    files = sorted(os.listdir(RAW_DIR))
    targets = []
    for fname in files:
        m = CAMPAIGN_FILE_RE.match(fname)
        if m:
            acct = m.group("acct")
            acct = str(int(acct)) if acct else None  # "032" → "32"
            targets.append((fname, acct, m.group("start"), m.group("end")))
        elif fname == special:
            targets.append((fname, "20", "2026-04-27", "2026-05-03"))

    # 已知账号的文件先处理, 便于给未知账号文件继承账号
    targets.sort(key=lambda t: (t[1] is None, t[0]))

    for fname, acct, start, end in targets:
        path = os.path.join(RAW_DIR, fname)
        try:
            # 全列按字符串读, 避免长数字 ID 被转成 float 丢失精度
            df = pd.read_excel(path, sheet_name="Data", header=0, dtype=str)
        except Exception as e:
            print("  [跳过] %s: %s" % (fname, e))
            continue

        # 日期来源: 文件内 日期 列 > 单日文件名 > 区间末日
        for _, r in df.iterrows():
            ad_id = _clean_text(r.get("广告计划 ID"), 40)
            if not ad_id or ad_id.lower() == "nan":
                continue
            date_str = ""
            if "日期" in df.columns:
                raw_date = str(r.get("日期", ""))
                m2 = re.search(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", raw_date)
                if m2:
                    date_str = "%s-%02d-%02d" % (
                        m2.group(1), int(m2.group(2)), int(m2.group(3)))
            if not date_str:
                date_str = start if start == end else end

            account = acct
            if account is None:
                account = acct_inherit.get(ad_id, "未知店铺")
            else:
                acct_inherit.setdefault(ad_id, account)
            platform = "TikTok-%s" % account

            spend = _num(r.get("成本"))
            revenue = _num(r.get("总收入"))
            conversions = _int(r.get("SKU 订单数"))
            roas = _num(r.get("ROI"))
            key = (ad_id, date_str)
            if key in rows:
                continue  # 重复导出(周期重叠文件), 保留首条
            rows[key] = {
                "ad_id": ad_id,
                "ad_name": _clean_text(r.get("广告计划名称"), 60),
                "platform": platform,
                "clicks": 0,
                "impressions": 0,
                "spend": round(spend, 2),
                "conversions": conversions,
                "conversion_value": round(revenue, 2),
                "ctr": 0,
                "cpc": round(spend / conversions, 2) if conversions else 0,
                "roas": round(roas, 2),
                "campaign_id": ad_id,
                "ad_group_id": "",
                "date": date_str,
            }
    return rows


# ── 2. 创意级数据 (视频素材粒度, 含曝光/点击) ────────────────────────

def parse_creative_files():
    rows = {}
    for fname in os.listdir(RAW_DIR):
        if not fname.startswith("creative data for product campaigns"):
            continue
        path = os.path.join(RAW_DIR, fname)
        # 数据窗口 2026-04-13 ~ 04-19, 统计值为窗口累计, 日期记为窗口末日
        m = re.search(r"(\d{4}-\d{2}-\d{2}).*?~.*?(\d{4}-\d{2}-\d{2})", fname)
        window_end = m.group(2) if m else "2026-04-19"
        try:
            # 全列按字符串读, 避免 19 位视频 ID 被转成 float 丢失精度
            df = pd.read_excel(path, sheet_name="Data", header=0, dtype=str)
        except Exception as e:
            print("  [跳过] %s: %s" % (fname, e))
            continue
        for _, r in df.iterrows():
            video_id = _clean_text(r.get("视频 ID"), 40)
            if not video_id or video_id.lower() == "nan":
                continue
            spend = _num(r.get("成本"))
            clicks = _int(r.get("商品广告点击数"))
            impressions = _int(r.get("商品广告曝光数"))
            conversions = _int(r.get("SKU 订单数"))
            revenue = _num(r.get("总收入"))
            if impressions == 0 and clicks == 0 and spend == 0:
                continue  # 完全无投放的空行
            rows[(video_id, window_end)] = {
                "ad_id": video_id,
                "ad_name": _clean_text(r.get("视频标题"), 60),
                "platform": "TikTok-创意素材",
                "clicks": clicks,
                "impressions": impressions,
                "spend": round(spend, 2),
                "conversions": conversions,
                "conversion_value": round(revenue, 2),
                "ctr": round(_num(r.get("商品广告点击率")) * 100, 2),
                "cpc": round(spend / clicks, 2) if clicks else 0,
                "roas": _num(r.get("ROI")),
                "campaign_id": _clean_text(r.get("广告计划 ID"), 40),
                "ad_group_id": "",
                "date": window_end,
            }
    return rows


# ── 3. 订单数据 → 商品销售聚合 ───────────────────────────────────────

def parse_order_files():
    """解析订单导出, 返回 (orders: {(order_id, sku_id): row}, sku_cost: {sku: cost})"""
    orders = {}
    sku_cost = {}

    order_file_re = re.compile(r"(订单|笔订单)")
    for fname in os.listdir(RAW_DIR):
        if not fname.endswith(".xlsx") or not order_file_re.search(fname):
            continue
        path = os.path.join(RAW_DIR, fname)
        try:
            xl = pd.ExcelFile(path)
        except Exception as e:
            print("  [跳过] %s: %s" % (fname, e))
            continue
        if "OrderSKUList" not in xl.sheet_names:
            continue

        # SKU 成本小表: [Seller SKU, 单价, 每单出库成本]
        if "Sheet1" in xl.sheet_names:
            try:
                cost_df = pd.read_excel(xl, sheet_name="Sheet1", header=None)
                for _, r in cost_df.iterrows():
                    sku = _clean_text(r.get(0), 30)
                    if re.fullmatch(r"[A-Z]{2}\d+", sku):
                        sku_cost.setdefault(sku, _num(r.get(2)))
            except Exception:
                pass

        try:
            # 全列按字符串读, 避免 18 位订单号被转成 float 丢失精度
            df = pd.read_excel(xl, sheet_name="OrderSKUList", header=0, dtype=str)
        except Exception as e:
            print("  [跳过] %s: %s" % (fname, e))
            continue
        if "Seller SKU" not in df.columns or df.shape[1] < 10:
            continue  # 仅订单号单列的文件, 无分析价值

        # 剔除描述行(第2行为字段说明)
        df = df[df["Order ID"].astype(str) != "Platform unique order ID."]

        for _, r in df.iterrows():
            order_id = _clean_text(r.get("Order ID"), 30)
            sku_id = _clean_text(r.get("SKU ID"), 30)
            if not order_id or order_id.lower() == "nan":
                continue
            # 剔除已取消订单
            status = str(r.get("Order Status", ""))
            cancelled = ("取消" in status) or (
                str(r.get("Cancelled Time", "nan")) not in ("nan", "", "None"))
            if cancelled:
                continue
            # Created Time 为 dd/mm/yyyy HH:MM:SS
            created = str(r.get("Created Time", ""))
            try:
                date_str = datetime.strptime(
                    created.split(" ")[0], "%d/%m/%Y").strftime("%Y-%m-%d")
            except ValueError:
                continue
            qty = _int(r.get("Quantity"), 1) or 1
            revenue = _num(r.get("SKU Subtotal After Discount"))
            seller_sku = _clean_text(r.get("Seller SKU"), 30)
            key = (order_id, sku_id)
            if key in orders:
                continue  # 多次导出重叠, 保留首条
            orders[key] = {
                "sku": seller_sku,
                "product_name": _clean_text(r.get("Product Name"), 60),
                "category": _clean_text(r.get("Product Category"), 30),
                "qty": qty,
                "revenue": revenue,
                "date": date_str,
            }
    return orders, sku_cost


def aggregate_products(orders, sku_cost):
    """按 (sku, date) 聚合订单为商品销售日数据"""
    groups = {}
    for o in orders.values():
        if not o["sku"]:
            continue
        key = (o["sku"], o["date"])
        g = groups.setdefault(key, {
            "product_name": o["product_name"],
            "category": o["category"],
            "sales_volume": 0,
            "revenue": 0.0,
        })
        g["sales_volume"] += o["qty"]
        g["revenue"] += o["revenue"]
        if not g["product_name"] and o["product_name"]:
            g["product_name"] = o["product_name"]
        if not g["category"] and o["category"]:
            g["category"] = o["category"]

    rows = []
    for (sku, date_str), g in sorted(groups.items()):
        unit_cost = sku_cost.get(sku, 0.0)
        vol = g["sales_volume"]
        rows.append({
            "sku": sku,
            "product_name": g["product_name"],
            "category": g["category"],
            "sales_volume": vol,
            "revenue": round(g["revenue"], 2),
            "cost": round(unit_cost * vol, 2),
            "inventory": 0,  # 原始数据无库存信息
            "avg_price": round(g["revenue"] / vol, 2) if vol else 0,
            "date": date_str,
        })
    return rows


def _write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main():
    if not os.path.isdir(RAW_DIR):
        print("错误: 未找到 %s" % RAW_DIR)
        sys.exit(1)
    os.makedirs(OUT_DIR, exist_ok=True)

    print("[1/3] 解析店铺广告计划文件 ...")
    campaign_rows = parse_campaign_files()
    print("      计划级广告记录: %d 条" % len(campaign_rows))

    print("[2/3] 解析创意级数据 ...")
    creative_rows = parse_creative_files()
    print("      创意素材记录: %d 条" % len(creative_rows))

    all_ads = list(campaign_rows.values()) + list(creative_rows.values())
    all_ads.sort(key=lambda r: (r["date"], r["platform"], r["ad_id"]))
    ads_path = os.path.join(OUT_DIR, "ads_performance.csv")
    _write_csv(ads_path, ADS_HEADER, all_ads)
    spend = sum(r["spend"] for r in all_ads)
    revenue = sum(r["conversion_value"] for r in all_ads)
    print("      写入 %s (共 %d 行, 总花费 $%.2f, 总收入 $%.2f)" % (
        ads_path, len(all_ads), spend, revenue))

    print("[3/3] 解析订单并聚合商品销售 ...")
    orders, sku_cost = parse_order_files()
    print("      有效订单行: %d, SKU 成本表: %d 个 SKU" % (len(orders), len(sku_cost)))
    product_rows = aggregate_products(orders, sku_cost)
    product_path = os.path.join(OUT_DIR, "product_sales.csv")
    _write_csv(product_path, PRODUCT_HEADER, product_rows)
    total_rev = sum(r["revenue"] for r in product_rows)
    total_vol = sum(r["sales_volume"] for r in product_rows)
    skus = len(set(r["sku"] for r in product_rows))
    print("      写入 %s (共 %d 行, %d 个 SKU, 总销量 %d, 总收入 ฿%.2f)" % (
        product_path, len(product_rows), skus, total_vol, total_rev))

    print("\n完成。使用真实数据运行应用: BIZ_DATA_DIR=data_real")


if __name__ == "__main__":
    main()
