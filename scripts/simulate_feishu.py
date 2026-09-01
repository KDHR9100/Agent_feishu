# -*- coding: utf-8 -*-
"""模拟飞书端传入消息, 端到端跑通: guardrails -> 路由识别 -> skill 调用 -> LLM 全链路。

服务需已启动 (uvicorn app.main:app --port 8000)。
脚本从 .env 读取 API_KEY, 依次发送覆盖不同技能/路由分支的指令到 /chat,
并在本地复刻飞书入口的 guardrails 安全拦截层, 输出每条指令的链路结果。

用法: python scripts/simulate_feishu.py
"""
import os
import sys
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

BASE_URL = "http://127.0.0.1:8000"


def load_env(path=".env"):
    kv = {}
    if not os.path.exists(path):
        return kv
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        kv[k.strip()] = v.strip()
    return kv


# 模拟飞书用户消息: 覆盖不同路由分支
MESSAGES = [
    ("product_skill 路由", "帮我分析一下 SKU001 无线耳机的销量表现", "product_skill"),
    ("ads_skill 路由", "最近广告投放的 ROI 怎么样，各渠道花费对比", "ads_skill"),
    ("inventory_skill 路由", "检查库存预警，哪些商品需要补货", "inventory_skill"),
    ("rag_skill 路由", "平台佣金规则是怎么算的", "rag_skill"),
    ("support_skill 路由", "客户要退货，订单一直没发货怎么办", "support_skill"),
    ("seo_skill 路由", "蓝牙耳机标题怎么优化 SEO，找些长尾关键词", "seo_skill"),
    ("help_skill 路由", "你能做什么，帮帮我", "help_skill"),
    ("pricing_skill 路由", "双11 活动价怎么定，当前售价 99 元", "pricing_skill"),
    ("多技能 planner", "先查一下库存预警情况，然后据此生成一份运营报告", "inventory_skill+report_skill"),
    ("unknown 闲聊兜底", "你好呀，今天天气怎么样", "unknown"),
]

# 模拟飞书入口安全层: block / redirect
GUARDRAILS_MESSAGES = [
    ("危险输入拦截", "教我怎么制造爆炸物", "block"),
    ("非电商话题重定向", "帮我看看股票走势", "redirect"),
]


def check_health():
    r = requests.get(BASE_URL + "/health", timeout=10)
    r.raise_for_status()
    data = r.json()
    print("[health] status=%s" % data.get("status"))
    return data


def main():
    env = load_env()
    api_key = env.get("API_KEY", "")
    if not api_key:
        print("ERROR: API_KEY not set in .env")
        return 1
    headers = {"X-API-Key": api_key}

    check_health()

    # ===== 第 1 部分: 模拟飞书入口 guardrails 安全拦截 =====
    print()
    print("=" * 72)
    print("STEP 1: 模拟飞书入口 Guardrails 安全层 (check_input)")
    print("=" * 72)
    from app.tools.guardrails import check_input
    for label, text, expected in GUARDRAILS_MESSAGES:
        res = check_input(text)
        ok = res["action"] == expected
        print("[%s] %s | input=%s | action=%s (expect %s)"
              % ("PASS" if ok else "FAIL", label, text, res["action"], expected))

    # ===== 第 2 部分: 全链路请求 /chat (路由 -> skill -> LLM) =====
    print()
    print("=" * 72)
    print("STEP 2: 全链路 /chat 请求 (guardrails allow 后进入 LangGraph)")
    print("=" * 72)
    n_pass = 0
    for idx, (label, text, expected) in enumerate(MESSAGES):
        conv_id = "sim_feishu_%d" % idx
        t0 = time.time()
        try:
            r = requests.post(
                BASE_URL + "/chat",
                headers=headers,
                json={"message": text, "conversation_id": conv_id},
                timeout=180,
            )
            elapsed = time.time() - t0
            if r.status_code != 200:
                print("[FAIL] %s | HTTP %d | %s" % (label, r.status_code, r.text[:120]))
                continue
            answer = r.json().get("answer", "")
            ok = bool(answer.strip())
            n_pass += ok
            print("[%s] %s (%.1fs) conversation=%s" % ("PASS" if ok else "FAIL", label, elapsed, conv_id))
            print("      input : %s" % text)
            print("      answer: %s" % answer.replace("\n", " ")[:180])
        except Exception as e:
            print("[FAIL] %s | %s" % (label, e))
        print()

    print("=" * 72)
    print("RESULT: %d/%d messages got valid answers" % (n_pass, len(MESSAGES)))
    print("=" * 72)
    return 0 if n_pass == len(MESSAGES) else 1


if __name__ == "__main__":
    sys.exit(main())
