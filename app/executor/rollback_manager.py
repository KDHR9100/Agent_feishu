# -*- coding: utf-8 -*-
"""L4 回滚管理器: 记录执行动作的 action_id 与旧值

规则: 执行后 1 小时(confirm_window)内未收到人工确认 -> 自动回滚到旧值。
巡检: 守护线程每 sweep_interval 秒扫一次; 也可手动调用 sweep_once() (测试友好)。
"""
import logging
import threading
import time
import uuid

logger = logging.getLogger("executor.rollback")


class RollbackManager:
    def __init__(self, store_api=None, confirm_window_seconds=3600,
                 sweep_interval_seconds=60, auto_start=False):
        from app.executor.platform_adapter import get_store_api
        self.store = store_api or get_store_api()
        self.confirm_window = confirm_window_seconds
        self.sweep_interval = sweep_interval_seconds
        self._records = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        if auto_start:
            self.start()

    # ---------- 记录 ----------
    def record(self, action, params, old_values, action_id=None,
               conversation_id="", rollbackable=True):
        """执行成功后登记, 等待人工确认; 返回 action_id"""
        action_id = action_id or uuid.uuid4().hex[:12]
        with self._lock:
            self._records[action_id] = {
                "action": action,
                "params": params,
                "old_values": old_values or {},
                "conversation_id": conversation_id,
                "executed_at": time.time(),
                "status": "awaiting_confirmation",  # awaiting_confirmation/confirmed/rolled_back
                "rollbackable": rollbackable,
            }
        logger.info(
            "[rollback] recorded action_id=%s action=%s old_values=%s window=%ds",
            action_id, action, old_values, self.confirm_window,
        )
        return action_id

    def confirm(self, action_id):
        """人工确认完成, 撤销自动回滚"""
        with self._lock:
            entry = self._records.get(action_id)
            if not entry or entry["status"] != "awaiting_confirmation":
                return False
            entry["status"] = "confirmed"
        logger.info("[rollback] action_id=%s confirmed by human", action_id)
        return True

    def get(self, action_id):
        with self._lock:
            return self._records.get(action_id)

    def pending_ids(self):
        with self._lock:
            return [k for k, v in self._records.items()
                    if v["status"] == "awaiting_confirmation"]

    # ---------- 回滚 ----------
    def rollback(self, action_id, reason="manual"):
        """按动作类型将店铺状态恢复到旧值"""
        with self._lock:
            entry = self._records.get(action_id)
            if not entry:
                return {"success": False, "reason": "not_found"}
            if entry["status"] == "confirmed":
                return {"success": False, "reason": "already_confirmed"}
            if entry["status"] == "rolled_back":
                return {"success": False, "reason": "already_rolled_back"}
            if not entry["rollbackable"]:
                entry["status"] = "rollback_failed"
                logger.warning("[rollback] action_id=%s not rollbackable, need human", action_id)
                return {"success": False, "reason": "not_rollbackable"}
            action, params, old_values = entry["action"], entry["params"], entry["old_values"]

        try:
            if action == "update_price":
                receipt = self.store.update_price(
                    params.get("product_id"), old_values.get("old_price"))
            elif action == "delist_product":
                receipt = self.store.relist_product(params.get("product_id"))
            else:
                return {"success": False, "reason": "unsupported_action"}
        except Exception as e:
            logger.error("[rollback] action_id=%s rollback error: %s", action_id, e)
            return {"success": False, "reason": "error:%s" % e}

        with self._lock:
            if action_id in self._records:
                self._records[action_id]["status"] = "rolled_back"
                self._records[action_id]["rollback_reason"] = reason
        logger.warning("[rollback] action_id=%s rolled back (%s)", action_id, reason)
        return {"success": True, "reason": reason, "receipt": receipt}

    # ---------- 巡检 ----------
    def sweep_once(self, now=None):
        """扫描超期未确认动作并自动回滚, 返回被回滚的 action_id 列表"""
        now = now or time.time()
        rolled = []
        for action_id in self.pending_ids():
            entry = self.get(action_id)
            if entry and now - entry["executed_at"] >= self.confirm_window:
                res = self.rollback(action_id, reason="confirm_timeout_1h")
                if res.get("success"):
                    rolled.append(action_id)
                    print("[rollback] 自动回滚 action_id=%s (1 小时内未收到人工确认)" % action_id)
        return rolled

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def _loop():
            while not self._stop.wait(self.sweep_interval):
                try:
                    self.sweep_once()
                except Exception as e:
                    logger.error("[rollback] sweep error: %s", e)

        self._thread = threading.Thread(target=_loop, daemon=True, name="rollback-sweeper")
        self._thread.start()
        logger.info("[rollback] sweeper started (interval=%ds window=%ds)",
                    self.sweep_interval, self.confirm_window)

    def shutdown(self):
        self._stop.set()


# 懒加载单例 (避免 import 期启动线程)
_instance = None
_instance_lock = threading.Lock()


def get_rollback_manager() -> RollbackManager:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = RollbackManager(auto_start=False)
        return _instance
