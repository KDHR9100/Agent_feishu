"""L4 损益优化沙盒 (决策核心层)

不靠 LLM 凭感觉做取舍, 靠数学模拟算最优解。
"""
from .profit_model import estimate_sales, estimate_profit, ad_lift_factor, roi
from .solver_engine import solve, evaluate_candidate, refine_with_scipy, solve_with_optuna
from .conflict_resolver import (
    ConflictResolver,
    detect_conflicts,
    get_conflict_resolver,
    is_conflicted,
    pareto_front,
)

__all__ = [
    "estimate_sales", "estimate_profit", "ad_lift_factor", "roi",
    "solve", "evaluate_candidate", "refine_with_scipy", "solve_with_optuna",
    "ConflictResolver", "detect_conflicts", "get_conflict_resolver",
    "is_conflicted", "pareto_front",
]
