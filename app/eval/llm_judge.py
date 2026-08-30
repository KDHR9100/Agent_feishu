"""
LLM-as-Judge evaluation script.
Evaluates routing accuracy + response quality using LLM scoring.

Usage:
  python -m app.eval.llm_judge --base-url http://10.132.226.232:1234/v1
  python -m app.eval.llm_judge  # uses config LLM
"""
import json
import time
import argparse
import logging
from pathlib import Path
from datetime import datetime

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_llm

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("llm_judge")

# ============================================================
# Test set: (question, expected_skill, reference_keywords)
# reference_keywords = key terms the response SHOULD contain
# ============================================================
EVAL_SET = [
    {
        "question": "帮我分析一下商品销量趋势",
        "expected_skill": "product_skill",
        "reference_keywords": ["销量", "趋势", "商品"],
    },
    {
        "question": "广告投放的ROI怎么样",
        "expected_skill": "ads_skill",
        "reference_keywords": ["ROI", "广告", "投放"],
    },
    {
        "question": "库存预警有哪些商品",
        "expected_skill": "inventory_skill",
        "reference_keywords": ["库存", "预警"],
    },
    {
        "question": "佣金规则是什么",
        "expected_skill": "rag_skill",
        "reference_keywords": ["佣金", "规则"],
    },
    {
        "question": "SEO关键词优化建议",
        "expected_skill": "seo_skill",
        "reference_keywords": ["SEO", "关键词", "优化"],
    },
    {
        "question": "我要退款订单号12345",
        "expected_skill": "support_skill",
        "reference_keywords": ["退款", "订单"],
    },
    {
        "question": "生成本周运营报告",
        "expected_skill": "report_skill",
        "reference_keywords": ["报告", "运营"],
    },
]

# ============================================================
# Judge prompt template
# ============================================================
JUDGE_PROMPT = """You are an evaluation judge for an e-commerce AI agent system.

User question: {question}
Expected skill: {expected_skill}
Actual routed skill: {actual_skill}
Agent response: {response}

Rate the response on these dimensions (1-5 scale):
1. relevance: Does the response address the user's question?
2. accuracy: Is the information factually correct and appropriate?
3. completeness: Does the response cover key aspects of the question?

Reference keywords that should appear: {reference_keywords}

Return ONLY valid JSON:
{{"relevance": <1-5>, "accuracy": <1-5>, "completeness": <1-5>, "reasoning": "<brief explanation>"}}"""


def get_judge_llm(base_url=None):
    if base_url:
        from app.utils.token_tracker import TokenTrackingHandler

        return ChatOpenAI(
            base_url=base_url, api_key="lm-studio",
            model="deepseek-r1-distill-nsfw-rp-vredux-proper.i1",
            temperature=0, timeout=30,
            callbacks=[TokenTrackingHandler()],
        )
    return get_llm()


def run_routing_eval():
    from app.agent.router import router
    results = []
    for item in EVAL_SET:
        state = {"user_input": item["question"], "conversation_id": "eval", "history": []}
        start = time.time()
        result = router(state)
        elapsed = time.time() - start
        actual = result["intent"]
        results.append({
            "question": item["question"],
            "expected": item["expected_skill"],
            "actual": actual,
            "correct": actual == item["expected_skill"],
            "latency_s": round(elapsed, 2),
        })
    acc = sum(1 for r in results if r["correct"]) / len(results)
    return {"routing_accuracy": acc, "details": results}


def run_judge_eval(judge_llm, responses=None):
    import re
    from app.utils.token_tracker import track_as
    from app.agent.router import router
    results = []
    for item in EVAL_SET:
        state = {"user_input": item["question"], "conversation_id": "ej", "history": []}
        rr = router(state)
        actual_skill = rr["intent"]
        resp_text = (responses or {}).get(item["question"], f"[{actual_skill} response]")
        prompt = JUDGE_PROMPT.format(
            question=item["question"], expected_skill=item["expected_skill"],
            actual_skill=actual_skill, response=resp_text,
            reference_keywords=", ".join(item["reference_keywords"]),
        )
        try:
            # 归属标签: 评审调用计入 "judge", 否则被记账层静默丢弃
            with track_as("judge"):
                resp = judge_llm.invoke([HumanMessage(content=prompt)])
            raw = resp.content if hasattr(resp, "content") else str(resp)
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            scores = json.loads(m.group(0)) if m else {"relevance": 0, "accuracy": 0, "completeness": 0}
        except Exception as e:
            scores = {"relevance": 0, "accuracy": 0, "completeness": 0, "error": str(e)}
        results.append({"question": item["question"], "routing_correct": actual_skill == item["expected_skill"], "scores": scores})
    n = len(results)
    return {
        "avg_relevance": round(sum(r["scores"].get("relevance", 0) for r in results) / n, 2),
        "avg_accuracy": round(sum(r["scores"].get("accuracy", 0) for r in results) / n, 2),
        "avg_completeness": round(sum(r["scores"].get("completeness", 0) for r in results) / n, 2),
        "details": results,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--mode", choices=["routing", "judge", "all"], default="all")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    # If --base-url specified, patch router to use that LLM
    if args.base_url:
        import app.agent.router as router_mod
        router_llm = ChatOpenAI(
            base_url=args.base_url, api_key="lm-studio",
            model="deepseek-r1-distill-nsfw-rp-vredux-proper.i1",
            temperature=0, timeout=30,
        )
        router_mod._llm_with_tools = None
        router_mod.get_llm = lambda: router_llm
        logger.info("Router LLM patched to: %s", args.base_url)

    report = {"timestamp": datetime.now().isoformat(), "mode": args.mode}
    if args.mode in ("routing", "all"):
        logger.info("Running routing eval...")
        report["routing"] = run_routing_eval()
        logger.info("Routing accuracy: %.0f%%", report["routing"]["routing_accuracy"] * 100)
    if args.mode in ("judge", "all"):
        logger.info("Running LLM-as-Judge...")
        judge_llm = get_judge_llm(args.base_url)
        report["judge"] = run_judge_eval(judge_llm)
        j = report["judge"]
        logger.info("Judge: rel=%.1f acc=%.1f comp=%.1f", j["avg_relevance"], j["avg_accuracy"], j["avg_completeness"])
    out_path = args.output or f"docs/eval_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Report saved: %s", out_path)
    print("\n" + "=" * 60)
    print("EVALUATION REPORT")
    print("=" * 60)
    if "routing" in report:
        print(f"Routing accuracy: {report['routing']['routing_accuracy']:.0%}")
        for d in report["routing"]["details"]:
            m = "Y" if d["correct"] else "N"
            print(f"  [{m}] {d['question'][:20]:<22} -> {d['actual']}")
    if "judge" in report:
        j = report["judge"]
        print(f"\nJudge (1-5): rel={j['avg_relevance']} acc={j['avg_accuracy']} comp={j['avg_completeness']}")
    print("=" * 60)


if __name__ == "__main__":
    main()