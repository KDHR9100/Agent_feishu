# -*- coding: utf-8 -*-
"""
RAG Evaluation Script
Tests 20 e-commerce questions and calculates recall rate.

Usage: python -m app.rag.eval.evaluate_rag
"""
import sys
import os
import time
import json

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from app.rag.vectorstore import vector_store  # noqa: E402


# 20 test questions about e-commerce platform rules
TEST_QUESTIONS = [
    # Commission & fees (5 questions)
    {"question": "平台佣金规则?", "expected_keywords": ["佣金", "结算", "保证金"], "category": "commission"},
    {"question": "商品佣金?", "expected_keywords": ["佣金", "商品", "结算"], "category": "commission"},
    {"question": "保证金?", "expected_keywords": ["保证金", "佣金", "平台"], "category": "commission"},
    {"question": "结算提款规则?", "expected_keywords": ["结算", "提款", "佣金"], "category": "commission"},
    {"question": "优惠促销佣金?", "expected_keywords": ["优惠", "促销", "佣金"], "category": "commission"},

    # Product listing & review (5 questions)
    {"question": "商品上架规则?", "expected_keywords": ["商品", "上架", "商品审核"], "category": "listing"},
    {"question": "商品审核?", "expected_keywords": ["商品审核", "商品", "规则"], "category": "listing"},
    {"question": "商品资质认证?", "expected_keywords": ["资质", "认证", "商品"], "category": "listing"},
    {"question": "店铺商品授权?", "expected_keywords": ["店铺", "授权", "商品"], "category": "listing"},
    {"question": "商品平台规则?", "expected_keywords": ["商品", "平台", "规则"], "category": "listing"},

    # Operations & logistics (5 questions)
    {"question": "发货物流规则?", "expected_keywords": ["发货", "物流", "售后"], "category": "operations"},
    {"question": "退款售后规则?", "expected_keywords": ["退款", "售后", "订单"], "category": "operations"},
    {"question": "库存管理?", "expected_keywords": ["库存", "商品", "发货"], "category": "operations"},
    {"question": "订单管理规则?", "expected_keywords": ["订单", "订单", "售后"], "category": "operations"},
    {"question": "客服售后规则?", "expected_keywords": ["客服", "售后", "订单"], "category": "operations"},

    # Marketing & advertising (5 questions)
    {"question": "广告投放规则?", "expected_keywords": ["广告", "投放", "促销"], "category": "marketing"},
    {"question": "促销活动规则?", "expected_keywords": ["促销", "优惠", "活动"], "category": "marketing"},
    {"question": "直通广告规则?", "expected_keywords": ["直通", "广告", "投放"], "category": "marketing"},
    {"question": "直播电商规则?", "expected_keywords": ["直播", "视频", "电商"], "category": "marketing"},
    {"question": "优惠券促销规则?", "expected_keywords": ["优惠", "促销", "平台"], "category": "marketing"},
]


def evaluate_rag():
    """Run RAG evaluation and calculate recall rate."""
    print("=" * 60)
    print("RAG Evaluation - 20 Test Questions")
    print("=" * 60)

    # Initialize vector store
    vector_store.initialize()

    if not vector_store.vector_store:
        print("ERROR: VectorStore not available")
        return

    results = []
    correct_count = 0
    total_count = len(TEST_QUESTIONS)

    for i, test in enumerate(TEST_QUESTIONS):
        question = test["question"]
        expected = test["expected_keywords"]
        category = test["category"]

        print(f"\n[{i+1}/{total_count}] Category: {category}")
        print(f"  Question: {question}")

        try:
            start_time = time.time()
            docs = vector_store.similarity_search(question, k=3)
            elapsed = time.time() - start_time

            # Check if any expected keyword appears in retrieved docs
            retrieved_text = " ".join([doc.page_content for doc in docs])
            matched_keywords = [kw for kw in expected if kw in retrieved_text]

            is_relevant = len(matched_keywords) > 0
            recall = len(matched_keywords) / len(expected) if expected else 0

            if is_relevant:
                correct_count += 1

            result = {
                "question": question,
                "category": category,
                "expected_keywords": expected,
                "matched_keywords": matched_keywords,
                "recall": recall,
                "is_relevant": is_relevant,
                "elapsed_ms": round(elapsed * 1000, 2),
                "retrieved_count": len(docs),
                "retrieved_preview": [doc.page_content[:100] for doc in docs],
            }
            results.append(result)

            print(f"  Matched: {matched_keywords}/{len(expected)} (recall: {recall:.0%})")
            print(f"  Relevant: {is_relevant} | Time: {elapsed*1000:.0f}ms")

        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({
                "question": question,
                "category": category,
                "error": str(e),
                "is_relevant": False,
            })

    # Summary
    print("\n" + "=" * 60)
    print("EVALUATION SUMMARY")
    print("=" * 60)
    print(f"Total questions: {total_count}")
    print(f"Relevant results: {correct_count}/{total_count} ({correct_count/total_count:.0%})")

    # By category
    categories = {}
    for r in results:
        cat = r["category"]
        if cat not in categories:
            categories[cat] = {"total": 0, "correct": 0}
        categories[cat]["total"] += 1
        if r.get("is_relevant"):
            categories[cat]["correct"] += 1

    print("\nBy Category:")
    for cat, stats in categories.items():
        print("  %s: %d/%d (%.0f%%)" % (
            cat, stats["correct"], stats["total"],
            stats["correct"] * 100.0 / stats["total"]))

    # Average recall
    recalls = [r.get("recall", 0) for r in results if "recall" in r]
    avg_recall = sum(recalls) / len(recalls) if recalls else 0
    print(f"\nAverage recall: {avg_recall:.0%}")

    # Average latency
    latencies = [r.get("elapsed_ms", 0) for r in results if "elapsed_ms" in r]
    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    print(f"Average latency: {avg_latency:.0f}ms")

    # Save results
    report = {
        "total_questions": total_count,
        "relevant_count": correct_count,
        "relevance_rate": correct_count / total_count,
        "average_recall": avg_recall,
        "average_latency_ms": avg_latency,
        "by_category": categories,
        "results": results,
    }

    report_path = os.path.join(os.path.dirname(__file__), "eval_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nReport saved to: {report_path}")


if __name__ == "__main__":
    evaluate_rag()
