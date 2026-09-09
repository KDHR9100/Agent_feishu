"""评测系统命令行入口。

用法::

    python -m evaluation.cli run --persona all --max-turns 8 --eval-mode mock --output reports/
    python -m evaluation.cli run --persona temu_operator
    python -m evaluation.cli list-personas
    python -m evaluation.cli validate

退出码：0 = 通过门禁；1 = 门禁未过；2 = 运行错误。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence

import structlog

from evaluation.adapters.agent_adapter import MockFeishuAgent, RealFeishuAgent
from evaluation.config import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_OUTPUT_DIR,
    EvalSettings,
    apply_yaml_overlay,
    load_yaml_overlay,
)
from evaluation.evaluators import build_evaluators, run_all_evaluators
from evaluation.llm_client import build_judge_client, build_sim_client
from evaluation.personas import get_persona, load_personas
from evaluation.reports import aggregate, generate_reports
from evaluation.simulator import build_orchestrator, build_user_agent
from evaluation.trajectory import TrajectoryWriter

logger = structlog.get_logger(__name__)


def _configure_structlog() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="%H:%M:%S"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(0),
    )


def _build_settings(args: argparse.Namespace) -> EvalSettings:
    """settings = 环境变量（EVAL_*）→ YAML 覆盖 → CLI 显式参数。"""

    settings = EvalSettings()
    overlay = load_yaml_overlay(Path(args.config) if args.config else None)
    if overlay:
        settings = apply_yaml_overlay(settings, overlay)
    if args.eval_mode:
        settings = settings.model_copy(update={"eval_mode": args.eval_mode})
    if args.max_turns:
        settings = settings.model_copy(update={"max_turns": int(args.max_turns)})
    return settings


def _select_personas(args: argparse.Namespace) -> List:
    if args.persona == "all":
        return load_personas()
    return [get_persona(args.persona)]


def cmd_run(args: argparse.Namespace) -> int:
    t0 = time.time()
    settings = _build_settings(args)
    personas = _select_personas(args)
    run_id = f"run-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    output_dir = Path(args.output).resolve() if args.output else DEFAULT_OUTPUT_DIR
    run_dir = output_dir / run_id
    logger.info(
        "eval_run_start",
        run_id=run_id,
        mode=settings.eval_mode,
        personas=[p.persona_id for p in personas],
        output=str(run_dir),
    )

    # ---- 组装模拟用户 / 被测 Agent / 裁判 ----
    sim_client = build_sim_client(settings)  # mock → None
    judge_client = build_judge_client(settings)  # mock → None
    user_agent = build_user_agent(settings.eval_mode, sim_client, settings.max_turns)

    if settings.eval_mode == "mock":
        adapter = MockFeishuAgent()
    else:
        adapter = RealFeishuAgent(run_dir=run_dir)

    orchestrator = build_orchestrator(user_agent, adapter, settings)
    evaluators = build_evaluators(settings, judge_client)

    # ---- 逐 episode：模拟对话 → 评测 → 落盘 ----
    episodes: List[dict] = []
    with TrajectoryWriter(run_dir / "trajectory.jsonl") as writer:
        for idx, persona in enumerate(personas):
            logger.info("episode_start", persona=persona.persona_id, index=idx)
            episode = orchestrator.run_episode(persona, run_id, idx)
            episode["_expected_tools"] = list(persona.expected_tools)  # type: ignore[assignment]
            episode["scores"] = run_all_evaluators(evaluators, episode, persona)
            episodes.append(episode)
            writer.write(episode)

    # ---- 聚合 + 报告 ----
    metrics = aggregate(episodes, settings)
    (run_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    paths = generate_reports(run_id, episodes, metrics, settings, run_dir)

    elapsed = time.time() - t0
    logger.info(
        "eval_run_done",
        run_id=run_id,
        overall=metrics.get("overall"),
        passed=metrics.get("passed"),
        elapsed_seconds=round(elapsed, 1),
        report=str(paths["markdown"]),
    )

    if settings.eval_mode == "mock":
        logger.info("mock_mode_note", hint="MODE=mock 仅管路验证, 分数无质量含义")
    if metrics.get("error_episodes"):
        return 2
    return 0 if metrics.get("passed") else 1


def cmd_list_personas(args: argparse.Namespace) -> int:  # noqa: ARG001
    for persona in load_personas():
        adversarial = " [adversarial]" if persona.is_adversarial else ""
        logger.info(
            "persona",
            persona_id=persona.persona_id,
            role=persona.role,
            goal=persona.goal[:60],
            extra=adversarial,
        )
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    personas = load_personas(Path(args.personas_file) if args.personas_file else None)
    logger.info("personas_valid", count=len(personas))
    if not Path(DEFAULT_CONFIG_PATH).exists():
        logger.warning("config_missing", path=str(DEFAULT_CONFIG_PATH))
        return 2
    overlay = load_yaml_overlay()
    logger.info("config_valid", keys=sorted(overlay.keys()))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evaluation.cli",
        description="FeishuAgent 合成用户评测系统",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="跑一次评测")
    run.add_argument("--persona", default="all", help="all 或 persona_id")
    run.add_argument("--max-turns", type=int, default=0, help="多轮上限（默认取配置 8）")
    run.add_argument(
        "--eval-mode", choices=["mock", "real"], default="",
        help="mock=零 token 管路验证; real=真实 LLM（默认读 EVAL_MODE）",
    )
    run.add_argument("--output", default="", help="产物目录（默认 evaluation/reports/）")
    run.add_argument("--config", default="", help="eval_config.yaml 路径")
    run.set_defaults(func=cmd_run)

    lst = sub.add_parser("list-personas", help="列出全部画像")
    lst.set_defaults(func=cmd_list_personas)

    val = sub.add_parser("validate", help="校验画像 YAML 与配置")
    val.add_argument("--personas-file", default="")
    val.set_defaults(func=cmd_validate)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    _configure_structlog()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        logger.warning("interrupted")
        return 130
    except Exception as exc:  # noqa: BLE001 - CLI 顶层兜底
        logger.error("cli_failed", error=str(exc))
        return 2


if __name__ == "__main__":
    sys.exit(main())
