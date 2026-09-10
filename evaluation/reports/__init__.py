"""Report 层：指标聚合 + Markdown/HTML 报告生成。"""

from evaluation.reports.metrics_aggregator import (
    aggregate,
    aggregate_by_dimension,
    aggregate_by_persona,
    aggregate_by_turn,
)
from evaluation.reports.report_generator import (
    generate_reports,
    load_previous_run,
    render_html,
    render_markdown,
)

__all__ = [
    "aggregate",
    "aggregate_by_dimension",
    "aggregate_by_persona",
    "aggregate_by_turn",
    "generate_reports",
    "load_previous_run",
    "render_html",
    "render_markdown",
]
