# -*- coding: utf-8 -*-
"""intent_probe 重跑补丁:
1) 修复 harness bug: O66(tasks键) / FB28(read_file) / R41(QueryCache直测)
2) 重跑被 429 污染的案例: O66b / C52 / C54 / HP63 / HP65 / HP64
3) 补采证据: L57 resolve-conflict 完整响应
限流口径 = API key 全局 30/min, 故 /chat 调用之间留足窗口。
"""
import json
import sys
import time
import shutil
import concurrent.futures

sys.path.insert(0, "/home/huajuanx/Agent_feishu")

import requests
from scripts.intent_probe import (
    send_chat, chat_case, record, _get, _post,
    ROOT, HDRS, BASE_URL, RUN_ID, phase_hotplug,
)

print("=== RETRY run=%s ===" % RUN_ID)

# ---------- 1. O66r: /tasks/status 用正确的 tasks 键 ----------
try:
    st, d = _get("/tasks/status")
    tasks = d.get("tasks") if isinstance(d, dict) else []
    names = [t.get("name") for t in tasks]
    record({"sid": "O66r", "phase": "ops-retry",
            "goal": "定时任务注册完整(库存/日报/周报) [修正harness读错jobs键]",
            "intent": "http:%s" % st,
            "answer": json.dumps(d, ensure_ascii=False)[:400],
            "passed": st == 200 and len(tasks) >= 3,
            "reason": "running=%s tasks=%s" % (d.get("running"), names)})
except Exception as e:
    record({"sid": "O66r", "phase": "ops-retry", "passed": False, "reason": str(e)[:150]})

# ---------- 2. FB28r: FileTool.read_file 路径穿越 ----------
try:
    from app.tools.file_tool import FileTool
    ft = FileTool()
    r1 = ft.read_file("../../etc/passwd")
    blocked = isinstance(r1, dict) and "error" in r1
    record({"sid": "FB28r", "phase": "fb-retry",
            "goal": "../../etc/passwd 读取必须被拦截 [修正harness调错方法名]",
            "intent": "filetool.read_file",
            "answer": json.dumps(r1, ensure_ascii=False)[:200],
            "passed": blocked,
            "reason": "拦截成功: %s" % r1.get("error", "")[:80] if blocked
                      else "危险: 返回了文件内容!"})
except Exception as e:
    record({"sid": "FB28r", "phase": "fb-retry", "passed": False, "reason": str(e)[:150]})

# ---------- 3. R41r: QueryCache LRU 直测(备份/还原缓存文件) ----------
cache_file = ROOT / "data" / "vectorstore" / "query_cache.json"
bak = ROOT / "data" / "vectorstore" / ("query_cache.bak.%s.json" % RUN_ID)
try:
    had_cache = cache_file.exists()
    if had_cache:
        shutil.copy(cache_file, bak)
    from app.rag.doc_manager import QueryCache
    qc = QueryCache()
    qc.cache = {}
    for i in range(205):
        qc.set("LRU探针查询%03d" % i, "sig0", {"r": i})
    in_mem = len(qc.cache)
    qc.save()
    disk = len(json.loads(cache_file.read_text(encoding="utf-8")))
    # 校验淘汰的是最旧条目: 最新一条应在缓存中
    newest_hit = qc.get("LRU探针查询204", "sig0") is not None
    oldest_gone = qc.get("LRU探针查询000", "sig0") is None
    record({"sid": "R41r", "phase": "rag-retry",
            "goal": "写入205条后LRU淘汰至<=200 [修正harness走错缓存层]",
            "intent": "in-mem:%d disk:%d" % (in_mem, disk),
            "passed": in_mem <= 200 and disk <= 200 and newest_hit and oldest_gone,
            "reason": "in-mem=%d disk=%d 最新命中=%s 最旧已淘汰=%s"
                      % (in_mem, disk, newest_hit, oldest_gone)})
except Exception as e:
    record({"sid": "R41r", "phase": "rag-retry", "passed": False, "reason": str(e)[:150]})
finally:
    try:
        if had_cache:
            shutil.copy(bak, cache_file)
            bak.unlink()
        elif cache_file.exists():
            cache_file.write_text("{}", encoding="utf-8")
    except OSError:
        pass

# ---------- 4. O66br: 周报生成 (上轮429) ----------
try:
    chat_case("O66br", "生成一份本周的业务价值报告", "生成业务价值周报",
              conv="probe_o66br_%s" % RUN_ID,
              expect=["report_skill", "data_analysis_skill"])
except Exception as e:
    record({"sid": "O66br", "phase": "chat-retry", "passed": False, "reason": str(e)[:150]})

# ---------- 5. C52r: 3并发不同会话 (上轮429) ----------
def _one(i):
    msgs = [("哪些商品库存低于预警线了？", "inventory_skill"),
            ("昨天广告ROI怎么样？", "ads_skill"),
            ("写一段小红书种草文案，主推夏季新品连衣裙", "content_skill")]
    m, exp = msgs[i]
    return chat_case("C52r%d" % (i + 1), m, "并发下路由不串线: %s" % exp,
                     conv="probe_c52r%d_%s" % (i, RUN_ID), expect=[exp])

try:
    with concurrent.futures.ThreadPoolExecutor(3) as ex:
        list(ex.map(_one, range(3)))
except Exception as e:
    record({"sid": "C52r", "phase": "rl-retry", "passed": False, "reason": str(e)[:150]})

print(">> 等待限流窗口滑动 65s ...")
time.sleep(65)

# ---------- 6. C54r: 重复消息路由缓存 (上轮429) ----------
try:
    conv = "probe_c54r_%s" % RUN_ID
    t0 = time.time()
    resp1, e1, err1 = send_chat("帮我看看全店库存健康状况", conv)
    t1 = time.time()
    resp2, e2, err2 = send_chat("帮我看看全店库存健康状况", conv)
    t2 = time.time()
    i1 = (resp1 or {}).get("intent")
    i2 = (resp2 or {}).get("intent")
    record({"sid": "C54r", "phase": "rl-retry",
            "goal": "相同消息第二次命中路由缓存(intent一致)",
            "intent": "%s/%s" % (i1, i2),
            "answer": (resp2 or {}).get("answer", "")[:150],
            "passed": bool(i1) and i1 == i2 and not err1 and not err2,
            "reason": "耗时 %.1fs/%.1fs err=%s/%s" % (t1 - t0, t2 - t1, err1, err2)})
except Exception as e:
    record({"sid": "C54r", "phase": "rl-retry", "passed": False, "reason": str(e)[:150]})

# ---------- 7. L57r: resolve-conflict 完整响应取证 ----------
try:
    st, d = _post("/optimize/resolve-conflict",
                  {"user_input": "我要利润率最高的同时销量也要最大"})
    keys = list(d.keys()) if isinstance(d, dict) else None
    record({"sid": "L57r", "phase": "l4-retry",
            "goal": "多目标冲突接口取证: 完整响应结构",
            "intent": "http:%s keys=%s" % (st, keys),
            "answer": json.dumps(d, ensure_ascii=False)[:800],
            "passed": st == 200,
            "reason": "完整结构见answer字段"})
except Exception as e:
    record({"sid": "L57r", "phase": "l4-retry", "passed": False, "reason": str(e)[:150]})

print(">> 等待限流窗口滑动 65s 后进入 hotplug ...")
time.sleep(65)

# ---------- 8. HOTPLUG 重跑 (上轮 HP63/HP65 429) ----------
try:
    phase_hotplug()
except Exception as e:
    record({"sid": "HP_retry", "phase": "hotplug-retry", "passed": False,
            "reason": str(e)[:150]})

print("=== RETRY DONE ===")
