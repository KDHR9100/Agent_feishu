"""Tests for WebSocketProcessManager"""
import time
import pytest
from unittest.mock import patch, MagicMock
from app.tools.ws_manager import WebSocketProcessManager


class TestWebSocketProcessManager:
    def test_init(self):
        mgr = WebSocketProcessManager()
        assert not mgr._running
        assert mgr._process is None
        assert mgr._restart_count == 0

    def test_get_status_before_start(self):
        mgr = WebSocketProcessManager()
        status = mgr.get_status()
        assert status["running"] is False
        assert status["pid"] is None
        assert status["restart_count"] == 0

    def test_start_without_credentials(self):
        mgr = WebSocketProcessManager()
        mgr.start("", "")
        assert not mgr._running
        assert mgr._process is None

    def test_stop_without_start(self):
        mgr = WebSocketProcessManager()
        mgr.stop()  # should not raise

    def test_get_status_structure(self):
        mgr = WebSocketProcessManager()
        status = mgr.get_status()
        assert "running" in status
        assert "pid" in status
        assert "exit_code" in status
        assert "restart_count" in status
        assert "max_restarts" in status

    def test_max_restarts_default(self):
        mgr = WebSocketProcessManager()
        assert mgr._max_restarts == 5

    def test_restart_cooldown_default(self):
        mgr = WebSocketProcessManager()
        assert mgr._restart_cooldown == 30

    @patch("app.tools.ws_manager.subprocess.Popen")
    def test_spawn_process(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc

        mgr = WebSocketProcessManager()
        mgr._app_id = "test_id"
        mgr._app_secret = "test_secret"
        mgr._spawn_process()

        mock_popen.assert_called_once()
        assert mgr._process is not None

    @patch("app.tools.ws_manager.subprocess.Popen")
    def test_terminate_process(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        mgr = WebSocketProcessManager()
        mgr._process = mock_proc
        mgr._terminate_process()

        mock_proc.terminate.assert_called_once()
        assert mgr._process is None
