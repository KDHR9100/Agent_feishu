"""指标聚合器：按 persona / 按维度 / 按轮次三个维度聚合，输出 JSON 中间产物。"""

from __future__ import annotations

from typing import Dict, List

import structlog

from evaluation.config import DIMENSIONS, EvalSettings

logger = structlog.get_logger(__name__)


def _dim_scores(episode: dict) -> Dict[str, dict]:
    return episode.get("scores", {}) or {}  # type: ignore[return-value]


def aggregate_by_dimension(episodes: List[dict], settings: EvalSettings) -> Dict[str, dict]:
    """按维度聚合：非 skipped episode 的均分 + 失败画像清单。"""

    result: Dict[str, dict] = {}
    for dim in DIMENSIONS:
        values: List[float] = []
        failed_personas: List[str] = []
        for ep in episodes:
            score = _dim_scores(ep).get(dim)
            if score is None or score.get("skipped"):
                continue
            values.append(float(score["score"]))
            if not score.get("passed"):
                failed_personas.append(str(ep.get("persona_id")))
        threshold = float(settings.thresholds.get(dim, 0.0))
        avg = round(sum(values) / len(values), 4) if values else None
        result[dim] = {
            "score": avg,
            "threshold": threshold,
            "passed": (avg is not None and avg >= threshold and not failed_personas),
            "episodes": len(values),
            "failed_personas": sorted(set(failed_personas)),
        }
    return result


def aggregate_by_persona(episodes: List[dict], settings: EvalSettings) -> Dict[str, dict]:
    """按画像聚合：各维分数 + 加权总分。"""

    result: Dict[str, dict] = {}
    for ep in episodes:
        pid = str(ep.get("persona_id"))
        dims: Dict[str, float] = {}
        skipped: List[str] = []
        for dim, score in _dim_scores(ep).items():
            if score.get("skipped"):
                skipped.append(dim)
            else:
                dims[dim] = round(float(score["score"]), 4)
        weighted = _weighted_score(dims, settings) if dims else None
        termination = (ep.get("termination") or {}).get("reason")
        result[pid] = {
            "goal": ep.get("goal", ""),
            "dimensions": dims,
            "skipped_dimensions": skipped,
            "weighted_score": weighted,
            # 全维 skipped（如对抗画像）不参与通过/失败统计
            "passed": True if not dims else (weighted >= settings.overall_gate and str(ep.get("error") or "") == ""),
            "turns_used": (ep.get("termination") or {}).get("turns_used", 0),
            "termination": termination,
        }
    return result


def aggregate_by_turn(episodes: List[dict]) -> Dict[str, dict]:
    """按轮次聚合：到达该轮的 episode 数 + 该轮工具调用正确率。"""

    buckets: Dict[int, Dict[str, float]] = {}
    for ep in episodes:
        expected: List[str] = list(ep.get("_expected_tools") or [])
        turns = ep.get("turns", []) or []
        for turn in turns:
            idx = int(turn.get("turn", 0))
            bucket = buckets.setdefault(idx, {"episodes": 0, "tool_correct": 0})
            bucket["episodes"] += 1
            called = [s for s in turn.get("skills_to_execute", []) or [] if s not in ("unknown",)]
            if not expected:
                correct = not called
            else:
                correct = all(c in expected for c in called)
            bucket["tool_correct"] += 1.0 if correct else 0.0
    return {
        str(idx): {
            "episodes": int(v["episodes"]),
            "tool_correct_rate": round(v["tool_correct"] / v["episodes"], 4),
        }
        for idx, v in sorted(buckets.items())
    }


def _weighted_score(dims: Dict[str, float], settings: EvalSettings) -> float:
    """加权总分（skipped 维度剔除后权重归一）。"""

    active = {d: v for d, v in dims.items() if d in settings.weights}
    if not active:
        return 0.0
    total_weight = sum(settings.weights[d] for d in active)
    if total_weight <= 0:
        return 0.0
    return round(
        sum(v * settings.weights[d] for d, v in active.items()) / total_weight, 4
    )


def aggregate(episodes: List[dict], settings: EvalSettings) -> dict:
    """总入口：产出 metrics.json 中间产物。"""

    by_dimension = aggregate_by_dimension(episodes, settings)
    by_persona = aggregate_by_persona(episodes, settings)
    by_turn = aggregate_by_turn(episodes)

    # 总分：各维均分的加权（skipped 维剔除）；安全一票否决
    active_dims = {
        d: v["score"] for d, v in by_dimension.items() if v["score"] is not None
    }
    overall = _weighted_score(active_dims, settings)
    safety = by_dimension.get("safety_violation", {})
    safety_tripped = (
        settings.safety_gate
        and safety.get("score") is not None
        and float(safety["score"]) < float(safety.get("threshold", 1.0))
    )
    if safety_tripped:
        overall = 0.0

    metrics = {
        "overall": overall,
        "passed": overall >= settings.overall_gate and not safety_tripped,
        "safety_gate_tripped": safety_tripped,
        "by_dimension": by_dimension,
        "by_persona": by_persona,
        "by_turn": by_turn,
        "episode_count": len(episodes),
        "error_episodes": [str(ep.get("persona_id")) for ep in episodes if ep.get("error")],
    }
    logger.info(
        "metrics_aggregated",
        overall=overall,
        passed=metrics["passed"],
        episodes=len(episodes),
    )
    return metrics
