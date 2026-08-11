# -*- coding: utf-8 -*-
"""端到端冒烟测试: 真实调用 skills_manifest.json 中的全部 13 个技能。

用法:
    python scripts/smoke_skills.py          # 跑全部技能
    python scripts/smoke_skills.py rag_skill pricing_skill   # 只跑指定技能

每个技能按 manifest 的 module/function 动态导入, 用贴近真实场景的中文输入调用,
校验返回值非空且无 error 标记, 输出 PASS/FAIL 汇总表。LLM 使用 .env 中的真实配置。
"""
import importlib
import inspect
import json
import os
import sqlite3
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

# 每个技能的代表性测试输入 (与真实飞书用户问法一致)
TEST_INPUTS = {
    "product_skill": "帮我分析 SKU001 无线耳机的销量表现和利润率",
    "ads_skill": "最近广告投放的 ROI 怎么样？各渠道花费和转化对比一下",
    "content_skill": "为无线蓝牙耳机写一段小红书种草文案，突出降噪和续航",
    "inventory_skill": "检查一下库存预警，哪些商品库存低需要补货",
    "competitor_skill": "帮我做一份无线耳机市场的竞品分析，重点是价格和卖点",
    "report_skill": "生成一份本周电商运营周报",
    "rag_skill": "平台佣金规则是怎么算的",
    "seo_skill": "帮我做蓝牙耳机的关键词研究，找一些长尾词",
    "support_skill": "帮我查一下订单的物流状态，客户说一直没收到货",
    "data_analysis_skill": "分析最近的销售趋势，有没有异常波动",
    "file_analysis_skill": "帮我分析这份销售数据表格",
    "help_skill": "帮助，你都能做什么",
    "pricing_skill": "爆款耳机当前售价 99 元，竞品均价 105 元，双11 想冲量，帮我定个活动价",
}


def check_db():
    """前置检查: 数据库表是否有种子数据, 空则初始化"""
    from app.config import config
    db_url = getattr(config, "DATABASE_URL", "") or os.environ.get(
        "DATABASE_URL", "sqlite:///./feishu_agent.db"
    )
    db_file = db_url.replace("sqlite:///", "")
    need_init = True
    if os.path.exists(db_file):
        try:
            conn = sqlite3.connect(db_file)
            rows = conn.execute("SELECT COUNT(*) FROM product_sales").fetchone()[0]
            ads = conn.execute("SELECT COUNT(*) FROM ads_performance").fetchone()[0]
            conn.close()
            print("[prereq] DB %s: product_sales=%d, ads_performance=%d" % (db_file, rows, ads))
            need_init = rows == 0
        except Exception as e:
            print("[prereq] DB check failed: %s" % e)
    if need_init:
        print("[prereq] DB empty or missing, running scripts/init_db.py ...")
        from app.models import init_db
        from scripts.init_db import seed_database
        init_db()
        seed_database()
        print("[prereq] DB seeded")


def check_llm():
    """前置检查: LLM 连通性 (真实调用一次)"""
    from app.config import get_llm
    from langchain_core.messages import HumanMessage
    t0 = time.time()
    resp = get_llm().invoke([HumanMessage(content="只回复两个字：正常")])
    text = resp.content if hasattr(resp, "content") else str(resp)
    print("[prereq] LLM ping OK in %.1fs, reply preview: %s" % (time.time() - t0, text[:50]))


def prepare_file_for_file_skill():
    """为 file_analysis_skill 准备一个真实 CSV 并走 file_parser_tool 解析"""
    csv_path = os.path.join(ROOT, "data", "uploads", "smoke_sample.csv")
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write("date,sku,product_name,sales_volume,revenue\n")
        rows = [
            ("2026-08-01", "SKU001", "Wireless Headphones", 130, 15600),
            ("2026-08-02", "SKU001", "Wireless Headphones", 96, 11520),
            ("2026-08-03", "SKU002", "Smart Watch", 54, 10800),
            ("2026-08-04", "SKU004", "Cotton T-Shirt", 320, 4800),
        ]
        for r in rows:
            f.write(",".join(str(x) for x in r) + "\n")
    from app.tools.file_parser_tool import file_parser_tool
    result = file_parser_tool.parse_local_file(csv_path)
    if result.get("error"):
        raise RuntimeError("parse sample csv failed: %s" % result["error"])
    content = file_parser_tool.format_file_summary(result, "smoke_sample.csv")
    return csv_path, content


def extract_text(result):
    """从技能返回值中提取可读文本用于预览"""
    if not isinstance(result, dict):
        return str(result)
    data = result.get("data", "")
    if isinstance(data, dict):
        return str(data.get("analysis") or data.get("summary") or data.get("response") or data)
    return str(data)


def run_skill(entry, file_ctx):
    """动态导入并调用单个技能, 返回 (ok, elapsed, preview, error)"""
    name = entry["name"]
    module = importlib.import_module(entry["module"])
    func = getattr(module, entry["function"])

    kwargs = {}
    params = inspect.signature(func).parameters
    if "user_input" in params:
        kwargs["user_input"] = TEST_INPUTS.get(name, "测试调用")
    if "file_path" in params and name == "file_analysis_skill":
        kwargs["file_path"] = file_ctx[0]
    if "file_content" in params and name == "file_analysis_skill":
        kwargs["file_content"] = file_ctx[1]
    if "tool_result" in params:
        kwargs["tool_result"] = {}

    t0 = time.time()
    try:
        result = func(**kwargs)
    except Exception as e:
        return False, time.time() - t0, "", "%s: %s\n%s" % (
            type(e).__name__, e, traceback.format_exc(limit=5))
    elapsed = time.time() - t0

    if isinstance(result, dict) and result.get("type") == "error":
        return False, elapsed, extract_text(result), "result type=error"
    if isinstance(result, dict):
        data = result.get("data")
        if isinstance(data, dict) and data.get("error"):
            return False, elapsed, extract_text(result), "data.error=%s" % data["error"]
    text = extract_text(result)
    if not text.strip():
        return False, elapsed, "", "empty output"
    return True, elapsed, text, ""


def main():
    only = set(sys.argv[1:])
    manifest = json.load(open(os.path.join(ROOT, "skills_manifest.json"), encoding="utf-8"))
    skills = [s for s in manifest["skills"] if not only or s["name"] in only]
    if only:
        missing = only - {s["name"] for s in skills}
        if missing:
            print("unknown skills: %s" % ", ".join(sorted(missing)))
            return 2

    print("=" * 70)
    print("PREREQUISITES")
    print("=" * 70)
    check_db()
    check_llm()
    file_ctx = prepare_file_for_file_skill()
    print("[prereq] sample csv parsed: %s" % file_ctx[0])

    print()
    print("=" * 70)
    print("RUNNING %d SKILLS" % len(skills))
    print("=" * 70)

    results = []
    for entry in skills:
        name = entry["name"]
        print("\n>>> %s ..." % name, flush=True)
        ok, elapsed, preview, err = run_skill(entry, file_ctx)
        results.append((name, ok, elapsed, preview, err))
        status = "PASS" if ok else "FAIL"
        print("[%s] %s (%.1fs)" % (status, name, elapsed))
        if ok:
            print("    output: %s" % preview.replace("\n", " ")[:200])
        else:
            print("    error: %s" % err.replace("\n", " | ")[:500])

    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    n_pass = 0
    for name, ok, elapsed, preview, err in results:
        n_pass += ok
        print("%-24s %-6s %6.1fs" % (name, "PASS" if ok else "FAIL", elapsed))
    print("-" * 70)
    print("%d/%d skills passed" % (n_pass, len(results)))
    return 0 if n_pass == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
