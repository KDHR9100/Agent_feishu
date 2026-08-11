# -*- coding: utf-8 -*-
"""合并: 主探针 + 重审(rejudge) + 重跑(retry), 输出最终口径统计"""
import json
import glob

R = "/home/huajuanx/Agent_feishu/data/reports"
main = [json.loads(l) for l in open(R + "/intent_probe_0806_142716.jsonl", encoding="utf-8") if l.strip()]
rj_files = sorted(glob.glob(R + "/intent_rejudge_*.jsonl"))
retry_files = sorted(glob.glob(R + "/intent_probe_0806_1638*.jsonl"))
rj = {x["sid"]: x for f in rj_files for x in (json.loads(l) for l in open(f, encoding="utf-8") if l.strip())}
retry = [json.loads(l) for f in retry_files for l in open(f, encoding="utf-8") if l.strip()]
retry_by_sid = {}
for x in retry:
    retry_by_sid.setdefault(x.get("sid"), x)

# 被重跑取代的原案例
SUPERSEDED = {"O66": "O66r", "O66b": "O66br", "C52": None, "C54": "C54r",
              "FB28": "FB28r", "R41": "R41r", "HP63": "HP63", "HP65": "HP65",
              "HP64": "HP64"}

final = []
for r in main:
    sid = r.get("sid")
    if sid in SUPERSEDED:
        rep = SUPERSEDED[sid]
        if rep is None:  # C52 -> 拆成3条
            for k in ("C52r1", "C52r2", "C52r3"):
                x = retry_by_sid.get(k)
                if x:
                    x2 = dict(x); x2["origin"] = "C52"; final.append(x2)
            continue
        x = retry_by_sid.get(rep)
        if x:
            x2 = dict(x); x2["origin"] = sid; final.append(x2)
        continue
    r2 = dict(r)
    if sid in rj:
        r2["judge_score"] = rj[sid]["new_score"]
        r2["judge_met"] = rj[sid]["new_met"]
        r2["judge_reason"] = rj[sid]["new_reason"]
        r2["rejudged"] = True
        # 意图达成翻正且无其它硬失败时, 视为通过
        hard_fail = any(k in (r.get("reason") or "") for k in ("缺关键内容", "出现禁止内容", "请求失败"))
        if rj[sid]["new_met"] and not hard_fail:
            r2["passed"] = True
    final.append(r2)

total = len(final)
passed = sum(1 for x in final if x.get("passed"))
judged = [x for x in final if x.get("judge_score") is not None]
met = sum(1 for x in judged if x.get("judge_met"))
avg = sum(x["judge_score"] for x in judged) / len(judged) if judged else 0

print("最终口径: 案例 %d | PASS %d | FAIL %d | 通过率 %.1f%%" % (
    total, passed, total - passed, 100.0 * passed / total))
print("意图评审: 参评 %d | 意图达成 %d | 达成率 %.1f%% | 平均分 %.2f/5" % (
    len(judged), met, 100.0 * met / len(judged), avg))

print("\n--- 按阶段 ---")
phases = {}
for x in final:
    p = x.get("phase", "?")
    phases.setdefault(p, [0, 0])
    phases[p][0] += 1
    phases[p][1] += 1 if x.get("passed") else 0
for p, (t, ok) in sorted(phases.items()):
    print("%-14s %2d/%2d 通过" % (p, ok, t))

print("\n--- 最终仍 FAIL 的案例 ---")
for x in final:
    if not x.get("passed"):
        print("%-8s | judge=%s met=%s | %s | %s" % (
            x.get("sid"), x.get("judge_score"), x.get("judge_met"),
            x.get("intent"), (x.get("reason") or "")[:110].replace("\n", " ")))

with open(R + "/intent_final_merged.jsonl", "w", encoding="utf-8") as f:
    for x in final:
        f.write(json.dumps(x, ensure_ascii=False) + "\n")
print("\nmerged ->", R + "/intent_final_merged.jsonl")
