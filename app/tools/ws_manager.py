"""WebSocket process manager with health check and auto-restart"""
import subprocess
import sys
import threading
import time
import logging

logger = logging.getLogger("app.ws_manager")


class WebSocketProcessManager:
    """管理飞书 WebSocket 客户端进程，提供健康检查和自动重启"""

    def __init__(self):
        self._process = None
        self._monitor_thread = None
        self._running = False
        self._app_id = None
        self._app_secret = None
        self._restart_count = 0
        self._max_restarts = 5
        self._restart_cooldown = 30  # seconds between restarts
        self._last_restart_time = 0

    def start(self, app_id: str, app_secret: str):
        """启动 WebSocket 客户端和监控线程"""
        if not app_id or not app_secret:
            logger.warning("Feishu credentials not configured, skipping WS client")
            return

        self._app_id = app_id
        self._app_secret = app_secret
        self._running = True
        self._spawn_process()
        self._start_monitor()

    def stop(self):
        """停止 WebSocket 客户端和监控线程"""
        self._running = False
        if self._process:
            self._terminate_process()
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5)

    def _spawn_process(self):
        """启动 WebSocket 子进程"""
        try:
            self._process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "app.tools.feishu_ws",
                    self._app_id,
                    self._app_secret,
                ],
                stdout=None,
                stderr=None,
                text=True,
            )
            logger.info("Feishu WS client started (PID: %d)", self._process.pid)
        except Exception as e:
            logger.error("Failed to start Feishu WS client: %s", str(e), exc_info=True)
            self._process = None

    def _terminate_process(self):
        """终止 WebSocket 子进程"""
        if self._process and self._process.poll() is None:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
                logger.info("Feishu WS client stopped (PID: %d)", self._process.pid)
            except subprocess.TimeoutExpired:
                logger.warning("Force killing Feishu WS client (PID: %d)", self._process.pid)
                self._process.kill()
                self._process.wait(timeout=3)
            except Exception as e:
                logger.error("Error stopping Feishu WS client: %s", str(e))
        self._process = None

    def _start_monitor(self):
        """启动后台监控线程"""
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="ws-health-monitor"
        )
        self._monitor_thread.start()
        logger.info("WS health monitor started")

    def _monitor_loop(self):
        """监控循环：检查进程健康状态，必要时自动重启"""
        while self._running:
            time.sleep(10)  # 每10秒检查一次

            if not self._running:
                break

            if self._process is None or self._process.poll() is not None:
                exit_code = self._process.poll() if self._process else "unknown"
                logger.warning("Feishu WS client process died (exit code: %s)", exit_code)

                if self._restart_count >= self._max_restarts:
                    logger.error(
                        "Max restarts (%d) reached, giving up on Feishu WS client",
                        self._max_restarts,
                    )
                    self._running = False
                    break

                now = time.time()
                if now - self._last_restart_time < self._restart_cooldown:
                    remaining = self._restart_cooldown - (now - self._last_restart_time)
                    logger.info("Restart cooldown: %.1fs remaining", remaining)
                    continue

                self._restart_count += 1
                self._last_restart_time = now
                logger.info(
                    "Auto-restarting Feishu WS client (attempt %d/%d)",
                    self._restart_count,
                    self._max_restarts,
                )
                self._spawn_process()

    def get_status(self) -> dict:
        """获取 WebSocket 进程状态"""
        is_alive = self._process is not None and self._process.poll() is None
        return {
            "running": is_alive,
            "pid": self._process.pid if self._process else None,
            "exit_code": self._process.poll() if self._process else None,
            "restart_count": self._restart_count,
            "max_restarts": self._max_restarts,
        }


ws_manager = WebSocketProcessManager()
