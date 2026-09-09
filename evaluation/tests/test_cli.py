"""CLI 端到端测试（mock 模式零 token）。"""

import json
from pathlib import Path

from evaluation.cli import main


class TestCLI:
    def test_run_single_persona_generates_reports(self, tmp_path: Path) -> None:
        rc = main([
            "run", "--persona", "temu_operator", "--eval-mode", "mock",
            "--output", str(tmp_path),
        ])
        assert rc == 0
        run_dirs = [d for d in tmp_path.iterdir() if d.is_dir() and d.name.startswith("run-")]
        assert len(run_dirs) == 1
        artifacts = {p.name for p in run_dirs[0].iterdir()}
        assert {"report.md", "report.html", "metrics.json", "trajectory.jsonl"} <= artifacts
        md = (run_dirs[0] / "report.md").read_text(encoding="utf-8")
        assert "temu_operator" in md and "MODE=mock" in md

    def test_run_all_personas_mock_smoke(self, tmp_path: Path) -> None:
        rc = main(["run", "--persona", "all", "--eval-mode", "mock", "--output", str(tmp_path)])
        assert rc == 0
        traj = next((tmp_path / d.name / "trajectory.jsonl")
                    for d in tmp_path.iterdir() if d.name.startswith("run-"))
        lines = [row for row in traj.read_text(encoding="utf-8").splitlines() if row.strip()]
        assert len(lines) >= 12, "13 个画像应产出 >=12 条 episode（全部成功）"
        for line in lines:
            episode = json.loads(line)
            assert episode["scores"], "每个 episode 必须有五维评分"
            assert not episode.get("error"), "mock 模式不应有运行错误"

    def test_list_personas(self, tmp_path: Path) -> None:
        assert main(["list-personas"]) == 0

    def test_validate(self, tmp_path: Path) -> None:
        assert main(["validate"]) == 0

    def test_unknown_persona_fails_cleanly(self, tmp_path: Path) -> None:
        rc = main([
            "run", "--persona", "no_such_persona", "--eval-mode", "mock",
            "--output", str(tmp_path),
        ])
        assert rc == 2
