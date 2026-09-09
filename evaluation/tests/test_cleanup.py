"""复核新增测试：卸载逻辑与 mock 无残留。

- 环境隔离快照/恢复 roundtrip（含原本未设置的键）；
- mock 全流程（CLI run）不加载任何 app.* 模块、不修改隔离环境变量，
  证明 mock 路径无补丁、无全局状态残留。
"""

import os
import sys
from pathlib import Path

from evaluation.adapters import apply_isolation_env, restore_env
from evaluation.cli import main

_ISOLATION_KEYS = ("ROUTER_CACHE_ENABLED", "DATABASE_URL", "BIZ_DATA_DIR", "APPROVAL_ENABLED")


def _app_modules() -> set:
    return {m for m in sys.modules if m == "app" or m.startswith("app.")}


class TestEnvIsolationRestore:
    def test_roundtrip_restores_all_keys(self, tmp_path: Path) -> None:
        # 预置两个不同初值，另两个保持未设置
        os.environ["ROUTER_CACHE_ENABLED"] = "true"
        os.environ["DATABASE_URL"] = "sqlite:///./orig.db"
        for key in ("BIZ_DATA_DIR", "APPROVAL_ENABLED"):
            os.environ.pop(key, None)

        snapshot = apply_isolation_env(tmp_path)
        assert os.environ["ROUTER_CACHE_ENABLED"] == "false"
        assert os.environ["DATABASE_URL"] == f"sqlite:///{tmp_path / 'agent.db'}"
        assert os.environ["BIZ_DATA_DIR"]
        assert os.environ["APPROVAL_ENABLED"] == "true"

        restore_env(snapshot)
        # 已设置的键恢复原值；未设置的键被删除（零残留）
        assert os.environ["ROUTER_CACHE_ENABLED"] == "true"
        assert os.environ["DATABASE_URL"] == "sqlite:///./orig.db"
        assert "BIZ_DATA_DIR" not in os.environ
        assert "APPROVAL_ENABLED" not in os.environ

    def test_restore_is_idempotent(self, tmp_path: Path) -> None:
        snapshot = apply_isolation_env(tmp_path)
        restore_env(snapshot)
        restore_env(snapshot)  # 重复恢复不应抛错


class TestMockPathNoResidue:
    def test_mock_run_loads_no_app_modules_and_keeps_env(self, tmp_path: Path) -> None:
        before_env = {k: os.environ.get(k) for k in _ISOLATION_KEYS}
        before_modules = _app_modules()

        rc = main([
            "run", "--persona", "temu_operator", "--eval-mode", "mock",
            "--output", str(tmp_path),
        ])
        assert rc == 0

        # mock 路径零补丁零加载：不新增任何 app.* 模块
        after_modules = _app_modules()
        assert after_modules == before_modules, (
            f"mock 模式不应加载主项目模块, 新增: {sorted(after_modules - before_modules)}"
        )
        # 隔离环境变量未被触碰
        after_env = {k: os.environ.get(k) for k in _ISOLATION_KEYS}
        assert after_env == before_env
