import time
import logging
from dataclasses import dataclass
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger("monitoring")


@dataclass
class MetricCounter:
    count: int = 0
    total_time: float = 0.0
    min_time: float = float("inf")
    max_time: float = 0.0
    errors: int = 0

    def add(self, duration: float, success: bool = True):
        self.count += 1
        self.total_time += duration
        if duration < self.min_time:
            self.min_time = duration
        if duration > self.max_time:
            self.max_time = duration
        if not success:
            self.errors += 1

    @property
    def avg_time(self) -> float:
        return self.total_time / self.count if self.count > 0 else 0.0


class MonitoringStats:
    def __init__(self):
        self.start_time = time.time()
        self.llm_calls = MetricCounter()
        self.embedding_calls = MetricCounter()
        self.feishu_api_calls = MetricCounter()
        self.rag_queries = MetricCounter()
        self.database_queries = MetricCounter()
        self.skill_calls: Dict[str, MetricCounter] = {}
        self.intent_counts: Dict[str, int] = {}
        self.total_tokens = {"prompt": 0, "completion": 0, "total": 0}
        self._lock = __import__("threading").Lock()

    def record_llm_call(
        self, duration: float, success: bool = True, token_usage: Optional[Dict] = None
    ):
        with self._lock:
            self.llm_calls.add(duration, success)
            if token_usage:
                self.total_tokens["prompt"] += token_usage.get("prompt_tokens", 0)
                self.total_tokens["completion"] += token_usage.get(
                    "completion_tokens", 0
                )
                self.total_tokens["total"] += token_usage.get("total_tokens", 0)

    def record_embedding_call(self, duration: float, success: bool = True):
        with self._lock:
            self.embedding_calls.add(duration, success)

    def record_feishu_api_call(self, duration: float, success: bool = True):
        with self._lock:
            self.feishu_api_calls.add(duration, success)

    def record_rag_query(self, duration: float, success: bool = True):
        with self._lock:
            self.rag_queries.add(duration, success)

    def record_database_query(self, duration: float, success: bool = True):
        with self._lock:
            self.database_queries.add(duration, success)

    def record_skill_call(self, skill_name: str, duration: float, success: bool = True):
        with self._lock:
            if skill_name not in self.skill_calls:
                self.skill_calls[skill_name] = MetricCounter()
            self.skill_calls[skill_name].add(duration, success)

    def record_intent(self, intent: str):
        with self._lock:
            self.intent_counts[intent] = self.intent_counts.get(intent, 0) + 1

    def get_health_status(self) -> Dict[str, Any]:
        uptime = time.time() - self.start_time
        min_time = (
            self.llm_calls.min_time * 1000
            if self.llm_calls.min_time != float("inf")
            else 0.0
        )
        max_time = self.llm_calls.max_time * 1000
        return {
            "status": "healthy",
            "uptime_seconds": int(uptime),
            "uptime_human": self._format_uptime(uptime),
            "timestamp": datetime.utcnow().isoformat(),
            "metrics": {
                "llm_calls": {
                    "count": self.llm_calls.count,
                    "avg_time_ms": round(self.llm_calls.avg_time * 1000, 2),
                    "min_time_ms": round(min_time, 2),
                    "max_time_ms": round(max_time, 2),
                    "error_rate": round(
                        self.llm_calls.errors / max(self.llm_calls.count, 1) * 100, 2
                    ),
                },
                "embedding_calls": {
                    "count": self.embedding_calls.count,
                    "avg_time_ms": round(self.embedding_calls.avg_time * 1000, 2),
                    "error_rate": round(
                        self.embedding_calls.errors
                        / max(self.embedding_calls.count, 1)
                        * 100,
                        2,
                    ),
                },
                "feishu_api_calls": {
                    "count": self.feishu_api_calls.count,
                    "avg_time_ms": round(self.feishu_api_calls.avg_time * 1000, 2),
                    "error_rate": round(
                        self.feishu_api_calls.errors
                        / max(self.feishu_api_calls.count, 1)
                        * 100,
                        2,
                    ),
                },
                "rag_queries": {
                    "count": self.rag_queries.count,
                    "avg_time_ms": round(self.rag_queries.avg_time * 1000, 2),
                    "error_rate": round(
                        self.rag_queries.errors / max(self.rag_queries.count, 1) * 100,
                        2,
                    ),
                },
                "database_queries": {
                    "count": self.database_queries.count,
                    "avg_time_ms": round(self.database_queries.avg_time * 1000, 2),
                    "error_rate": round(
                        self.database_queries.errors
                        / max(self.database_queries.count, 1)
                        * 100,
                        2,
                    ),
                },
            },
            "intent_distribution": self.intent_counts.copy(),
            "skill_distribution": {k: v.count for k, v in self.skill_calls.items()},
            "token_consumption": self.total_tokens.copy(),
        }

    def get_jingang_consumption(self) -> Dict[str, Any]:
        return {
            "description": "Resource consumption statistics (Jingang Consumption)",
            "total_llm_calls": self.llm_calls.count,
            "total_embedding_calls": self.embedding_calls.count,
            "total_feishu_calls": self.feishu_api_calls.count,
            "total_rag_queries": self.rag_queries.count,
            "total_database_queries": self.database_queries.count,
            "total_tokens": self.total_tokens.copy(),
            "token_breakdown": {
                "prompt_tokens": self.total_tokens["prompt"],
                "completion_tokens": self.total_tokens["completion"],
                "total_tokens": self.total_tokens["total"],
            },
            "avg_llm_response_time_ms": round(self.llm_calls.avg_time * 1000, 2),
            "error_summary": {
                "llm_errors": self.llm_calls.errors,
                "embedding_errors": self.embedding_calls.errors,
                "feishu_errors": self.feishu_api_calls.errors,
                "rag_errors": self.rag_queries.errors,
                "database_errors": self.database_queries.errors,
            },
            "intent_summary": self.intent_counts.copy(),
            "skill_summary": {
                k: {"count": v.count, "avg_time_ms": round(v.avg_time * 1000, 2)}
                for k, v in self.skill_calls.items()
            },
        }

    def _format_uptime(self, seconds: float) -> str:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        if hours > 0:
            return f"{hours}h {minutes}m {secs}s"
        elif minutes > 0:
            return f"{minutes}m {secs}s"
        else:
            return f"{secs}s"


monitoring_stats = MonitoringStats()
