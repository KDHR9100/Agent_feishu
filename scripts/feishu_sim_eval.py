# -*- coding: utf-8 -*-
"""
模拟飞书 WS 通道核验: 用户请求 → 路由意图 → skill 执行 → 执行结果

与 app/tools/feishu_ws.py 的消息处理链同构:
  check_input guardrails → agent.stream({user_input, conversation_id})
  → 抓取 router / planner / skill_executor 各节点状态 → answer

每个用例预置三层期望:
  expected_intent : 路由层应识别的 skill 组合 (router.skills_to_execute)
  expected_skills : 执行层应实际运行的 skill 组合 (skill_results[*].skill)
  must_any        : 结果层 answer 应命中的关键词 (至少一个)

用法 (WSL conda 环境, 项目根目录):
  /home/huajuanx/miniconda3/envs/feishuagent/bin/python scripts/feishu_sim_eval.py
"""
import io
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from app.tools.guardrails import check_input  # noqa: E402
from app.agent.workflow import agent  # noqa: E402

# 兜底/失败话术黑名单: answer 出现即视为请求未完成
FALLBACK_MARKS = [
    "无法处理您的请求", "无法完成", "出现了错误", "系统繁忙",
    "稍后再试", "无法回答", "不在我的服务", "抱歉，我无法处理",
]

# ============================================================
# 用例定义: 电商运营场景, 措辞避开高危审批关键词, 保证请求可完成
# 期望组合依据 skills_manifest.json 职责定义:
#   - 单一领域日常分析归领域技能 (product/inventory/ads...)
#   - data_analysis_skill 仅跨领域综合分析
#   - planner 可能对"写话术/出报告"类请求做多步分解, 期望需覆盖合理组合
# ============================================================
CASES = [
    # ---------- F1: 单技能直达 ----------
    dict(id="F1-01", scene="库存查询",
         msg="查询 SKU-A001 的当前库存和可售数量",
         expected_intent=[["inventory_skill"]],
         expected_skills=[["inventory_skill"]],
         must_any=["SKU-A001", "库存", "可售", "数量"]),
    dict(id="F1-02", scene="商品查询",
         msg="查看 SKU-A001 的商品详情和上架状态",
         expected_intent=[["product_skill"]],
         expected_skills=[["product_skill"]],
         must_any=["SKU-A001", "商品", "上架", "详情"]),
    dict(id="F1-03", scene="广告分析",
         msg="分析本周广告投放的ROI和花费情况",
         expected_intent=[["ads_skill"]],
         expected_skills=[["ads_skill"]],
         must_any=["ROI", "花费", "广告", "投放", "点击"]),
    dict(id="F1-04", scene="竞品分析",
         msg="分析竞品的定价策略和近期促销打法",
         expected_intent=[["competitor_skill"]],
         expected_skills=[["competitor_skill"]],
         must_any=["竞品", "定价", "促销", "竞争"]),
    dict(id="F1-06", scene="SEO优化",
         msg="帮我优化无线蓝牙耳机商品标题的搜索关键词",
         expected_intent=[["seo_skill"]],
         expected_skills=[["seo_skill"]],
         must_any=["蓝牙", "耳机", "关键词", "标题", "SEO", "搜索"]),
    dict(id="F1-07", scene="客服话术",
         msg="顾客反馈物流3天没更新很生气，帮我写一段安抚回复话术",
         expected_intent=[["support_skill"]],
         expected_skills=[["support_skill"]],
         must_any=["物流", "抱歉", "亲", "您", "安抚"]),
    dict(id="F1-08", scene="销售分析",
         msg="分析最近7天的销售趋势，哪个品类卖得最好",
         expected_intent=[["product_skill"], ["data_analysis_skill"]],
         expected_skills=[["product_skill"], ["data_analysis_skill"]],
         must_any=["销售", "品类", "趋势", "销量"]),
    dict(id="F1-09", scene="日报生成",
         msg="帮我生成今天的运营日报，总结销售和库存整体情况",
         expected_intent=[["report_skill"],
                          ["data_analysis_skill", "report_skill"],
                          ["product_skill", "report_skill"],
                          ["product_skill", "inventory_skill", "report_skill"],
                          ["inventory_skill", "report_skill"]],
         expected_skills=[["report_skill"],
                          ["data_analysis_skill", "report_skill"],
                          ["product_skill", "report_skill"],
                          ["product_skill", "inventory_skill", "report_skill"],
                          ["inventory_skill", "report_skill"]],
         must_any=["日报", "销售", "运营", "总结"]),
    dict(id="F1-10", scene="规则咨询",
         msg="平台佣金是怎么计算的？结算周期是多久？",
         expected_intent=[["rag_skill"]],
         expected_skills=[["rag_skill"]],
         must_any=["佣金", "结算", "保证金"]),
    dict(id="F1-11", scene="定价建议",
         msg="新品 SKU-B002 成本价59元，帮我给出定价建议",
         expected_intent=[["pricing_skill"]],
         expected_skills=[["pricing_skill"]],
         must_any=["定价", "价格", "SKU-B002", "毛利", "建议"]),
    dict(id="F1-12", scene="能力询问",
         msg="你能帮我处理哪些电商运营工作？",
         expected_intent=[["help_skill"]],
         expected_skills=[["help_skill"]],
         must_any=["库存", "广告", "商品", "分析", "技能"]),

    # ---------- F2: 多步计划 ----------
    dict(id="F2-01", scene="竞品→定价",
         msg="先分析竞品的价格带，再给我们同类款一个定价参考",
         expected_intent=[["competitor_skill", "pricing_skill"],
                          ["competitor_skill"],
                          ["pricing_skill"]],
         expected_skills=[["competitor_skill", "pricing_skill"],
                          ["competitor_skill"],
                          ["pricing_skill"]],
         must_any=["定价", "竞品", "价格"]),
    dict(id="F2-02", scene="分析→日报",
         msg="分析昨天的销售数据，然后生成一份运营日报",
         expected_intent=[["data_analysis_skill", "report_skill"],
                          ["product_skill", "report_skill"],
                          ["report_skill"],
                          ["data_analysis_skill"]],
         expected_skills=[["data_analysis_skill", "report_skill"],
                          ["product_skill", "report_skill"],
                          ["report_skill"],
                          ["data_analysis_skill"]],
         must_any=["日报", "销售", "报告", "总结"]),

    # ---------- F3: 通道护栏 (WS 层 guardrails) ----------
    dict(id="F3-01", scene="话题护栏",
         msg="这只股票能买吗",
         expected_guard=True,
         expected_intent=[], expected_skills=[], must_any=[]),
]


def match_combo(actual, alternatives):
    """actual 的 skill 集合命中 alternatives 任一组合即通过"""
    a = set(actual or [])
    for combo in alternatives:
        if a == set(combo):
            return True
    return False


def run_case(case, interval):
    t0 = time.time()
    v = {"id": case["id"], "scene": case["scene"], "msg": case["msg"],
         "intent_ok": False, "skill_ok": False, "result_ok": False}

    # ---- 通道层: guardrails (与 feishu_ws.py L468 同构) ----
    g = check_input(case["msg"])
    v["guard_action"] = g["action"]
    if g["action"] in ("block", "redirect"):
        v["answer"] = g.get("message", "")[:200]
        v["elapsed"] = round(time.time() - t0, 2)
        if case.get("expected_guard"):
            v.update(intent_ok=True, skill_ok=True, result_ok=True,
                     passed=True, note="guardrails %s, 与 WS 通道行为一致" % g["action"])
        else:
            v.update(passed=False, failure_type="guardrail_false_positive",
                     note="正常业务请求被 guardrails 拦截(%s), 请求未完成" % g["action"])
        return v
    if case.get("expected_guard"):
        v.update(passed=False, failure_type="guardrail_miss",
                 note="应被护栏拦截的请求放行进 Agent",
                 elapsed=round(time.time() - t0, 2))
        return v

    # ---- Agent 执行 (与 feishu_ws.py L481-539 同构) ----
    conv_id = "sim_feishu_%s_%d" % (case["id"], int(time.time()))
    agent_input = {"user_input": case["msg"], "conversation_id": conv_id}
    router_skills, plan, final_state = [], None, None
    try:
        for chunk in agent.stream(agent_input):
            for node_name, node_state in chunk.items():
                if node_name == "router":
                    router_skills = node_state.get("skills_to_execute", [])
                elif node_name == "planner":
                    plan = node_state.get("execution_plan")
                final_state = node_state
    except Exception as e:
        v.update(passed=False, failure_type="error",
                 note="agent.stream 异常: %s" % e,
                 elapsed=round(time.time() - t0, 2))
        return v

    v["actual_intent"] = router_skills
    v["plan"] = [s.get("skill") for s in (plan or [])] if plan else []
    final_state = final_state or {}
    answer = final_state.get("answer", "") or ""
    skill_results = final_state.get("skill_results") or []
    executed = [r.get("skill") for r in skill_results]
    tool_result = final_state.get("tool_result") or {}
    v["actual_skills"] = executed
    v["answer"] = answer[:300]
    v["tool_result_type"] = tool_result.get("type", "")

    # ---- 第1层: 路由意图 ----
    v["intent_ok"] = match_combo(router_skills, case["expected_intent"])

    # ---- 第2层: skill 执行 ----
    # approval_required 且无 skill 执行记录 = 被审批门挂起, 请求未完成
    # approval_required 但有执行记录 = 建议类输出已产出, 仅"执行动作"需审批
    if tool_result.get("type") == "approval_required" and not executed:
        v["skill_ok"] = False
        v["failure_type"] = "approval_gate"
        v["note"] = "请求被审批门挂起, skill 未执行, 用户请求未完成"
    elif not executed:
        v["skill_ok"] = False
        v["failure_type"] = v.get("failure_type") or "no_skill_executed"
        v["note"] = "无任何 skill 实际执行"
    else:
        v["skill_ok"] = match_combo(executed, case["expected_skills"])
        if tool_result.get("type") == "approval_required":
            v["note"] = "skill 已执行并给出建议; 实际改价等动作需人工审批(高危操作设计)"

    # ---- 第3层: 执行结果 (请求是否被完成) ----
    hit = [k for k in case["must_any"] if k in answer]
    fallback_hit = [m for m in FALLBACK_MARKS if m in answer]
    v["keyword_hits"] = hit
    if not answer.strip():
        v["result_ok"] = False
        v["failure_type"] = v.get("failure_type") or "empty_answer"
    elif fallback_hit:
        v["result_ok"] = False
        v["failure_type"] = v.get("failure_type") or "fallback_answer"
        v["note"] = "answer 命中兜底话术: %s" % fallback_hit
    elif case["must_any"] and not hit:
        v["result_ok"] = False
        v["failure_type"] = v.get("failure_type") or "off_target"
        v["note"] = "answer 未命中任何期望关键词 %s" % case["must_any"]
    else:
        v["result_ok"] = True

    v["passed"] = v["intent_ok"] and v["skill_ok"] and v["result_ok"]
    v["elapsed"] = round(time.time() - t0, 2)
    if v["passed"]:
        v.pop("failure_type", None)
    elif "failure_type" not in v:
        layers = []
        if not v["intent_ok"]:
            layers.append("意图(%s≠%s)" % (router_skills, case["expected_intent"][0]))
        if not v["skill_ok"]:
            layers.append("执行(%s≠%s)" % (executed, case["expected_skills"][0]))
        v["failure_type"] = "layer_mismatch"
        v["note"] = "不一致层: " + "; ".join(layers)
    time.sleep(interval)
    return v


def main():
    interval = float(sys.argv[sys.argv.index("--interval") + 1]) if "--interval" in sys.argv else 1.0
    only = sys.argv[sys.argv.index("--cases") + 1].split(",") if "--cases" in sys.argv else None
    cases = [c for c in CASES if not only or c["id"] in only]

    print("模拟飞书通道核验: %d 个用例" % len(cases))
    results = []
    for case in cases:
        print("  [%s] %s ..." % (case["id"], case["scene"]), flush=True)
        v = run_case(case, interval)
        marks = "".join("✓" if v[k] else "✗" for k in ("intent_ok", "skill_ok", "result_ok"))
        status = "PASS" if v.get("passed") else "FAIL(%s)" % v.get("failure_type", "?")
        print("    %s [意图/执行/结果=%s] %.1fs" % (status, marks, v["elapsed"]), flush=True)
        if not v.get("passed"):
            print("    意图: 期望%s 实际%s" % (case["expected_intent"], v.get("actual_intent")), flush=True)
            print("    执行: 期望%s 实际%s" % (case["expected_skills"], v.get("actual_skills")), flush=True)
            print("    结果: %s" % (v.get("note") or v.get("answer", "")[:120]), flush=True)
        results.append(v)

    total = len(results)
    passed = sum(1 for r in results if r.get("passed"))
    intent_pass = sum(1 for r in results if r.get("intent_ok"))
    skill_pass = sum(1 for r in results if r.get("skill_ok"))
    result_pass = sum(1 for r in results if r.get("result_ok"))

    print("\n" + "=" * 78)
    print("总计 %d | 通过 %d (%.1f%%)" % (total, passed, 100.0 * passed / max(total, 1)))
    print("逐层达成: 意图 %d/%d | skill执行 %d/%d | 结果完成 %d/%d"
          % (intent_pass, total, skill_pass, total, result_pass, total))
    for r in results:
        if not r.get("passed"):
            print("[FAIL] %-6s %-10s %s" % (r["id"], r["scene"], r.get("failure_type", "")))
            if r.get("note"):
                print("       %s" % r["note"])

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_dir = PROJECT_ROOT / "data" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / ("feishu_sim_%s.json" % ts)
    md_path = report_dir / ("feishu_sim_%s.md" % ts)
    with io.open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    lines = ["# 模拟飞书通道核验报告 %s" % ts, "",
             "总计 %d | 通过 %d (%.1f%%)" % (total, passed, 100.0 * passed / max(total, 1)),
             "逐层: 意图 %d/%d | skill %d/%d | 结果 %d/%d" % (
                 intent_pass, total, skill_pass, total, result_pass, total), "",
             "| ID | 场景 | 意图 | 执行 | 结果 | 耗时 | 状态 |",
             "|---|---|---|---|---|---|---|"]
    for r in results:
        lines.append("| %s | %s | %s | %s | %s | %.1fs | %s |" % (
            r["id"], r["scene"],
            "✓" if r.get("intent_ok") else "✗",
            "✓" if r.get("skill_ok") else "✗",
            "✓" if r.get("result_ok") else "✗",
            r.get("elapsed", 0),
            "PASS" if r.get("passed") else "FAIL:%s" % r.get("failure_type", "")))
    lines.append("")
    for r in results:
        if not r.get("passed"):
            lines.append("## %s %s" % (r["id"], r["scene"]))
            lines.append("- 消息: %s" % r["msg"])
            lines.append("- 意图: 实际 %s" % r.get("actual_intent"))
            lines.append("- 执行: 实际 %s" % r.get("actual_skills"))
            lines.append("- 结果: %s" % (r.get("note") or ""))
            lines.append("- 回复片段: %s" % r.get("answer", "")[:200])
            lines.append("")
    with io.open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n结果已保存:\n  JSON: %s\n  报告: %s" % (json_path, md_path))


if __name__ == "__main__":
    main()
