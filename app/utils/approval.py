"""高风险操作审批队列 - 飞书卡片人工审批机制"""
import logging
import os
import time
import uuid
import threading
from typing import Dict, Optional, Callable, Any

logger = logging.getLogger("approval")

# 审批超时时间(秒)
APPROVAL_TIMEOUT = int(os.getenv("APPROVAL_TIMEOUT", "300"))


class ApprovalManager:
    """管理高风险操作的审批流程"""

    def __init__(self):
        self._pending: Dict[str, dict] = {}
        self._lock = threading.Lock()

    def create_approval(
        self,
        action_name: str,
        action_func: Callable,
        action_args: tuple = (),
        action_kwargs: dict = None,
        conversation_id: str = "",
        description: str = "",
    ) -> str:
        """创建审批请求, 返回 approval_id"""
        approval_id = str(uuid.uuid4())[:12]
        with self._lock:
            self._pending[approval_id] = {
                "action_name": action_name,
                "action_func": action_func,
                "action_args": action_args,
                "action_kwargs": action_kwargs or {},
                "conversation_id": conversation_id,
                "description": description,
                "created_at": time.time(),
                "status": "pending",
                "event": threading.Event(),
                "approved": None,
            }
        logger.info(
            "[approval] created %s for action=%s, timeout=%ds",
            approval_id, action_name, APPROVAL_TIMEOUT,
        )
        return approval_id

    def approve(self, approval_id: str) -> Optional[Any]:
        """批准并执行操作"""
        with self._lock:
            entry = self._pending.pop(approval_id, None)
        if not entry:
            logger.warning("[approval] %s not found or expired", approval_id)
            return None
        if time.time() - entry["created_at"] > APPROVAL_TIMEOUT:
            logger.info("[approval] %s expired", approval_id)
            return None
        logger.info("[approval] %s approved, executing %s", approval_id, entry["action_name"])
        return entry["action_func"](*entry["action_args"], **entry["action_kwargs"])

    def reject(self, approval_id: str) -> bool:
        """拒绝操作"""
        with self._lock:
            entry = self._pending.pop(approval_id, None)
        if entry:
            logger.info("[approval] %s rejected", approval_id)
            return True
        return False

    def resolve(self, approval_id: str, approved: bool) -> bool:
        """由外部回调（如 /approval/resolve）解决审批，唤醒等待方。
        不弹出 entry，由 wait_decision 读取后清理。"""
        with self._lock:
            entry = self._pending.get(approval_id)
            if not entry:
                return False
            entry["approved"] = bool(approved)
            entry["status"] = "approved" if approved else "rejected"
            ev = entry.get("event")
        if ev:
            ev.set()
        logger.info("[approval] %s resolved approved=%s", approval_id, approved)
        return True

    def wait_decision(self, approval_id: str, timeout: float = None) -> bool:
        """阻塞等待人工决策，返回是否批准（超时/拒绝均为 False）"""
        with self._lock:
            entry = self._pending.get(approval_id)
            ev = entry.get("event") if entry else None
        if ev is None:
            return False
        ev.wait(timeout if timeout is not None else APPROVAL_TIMEOUT)
        with self._lock:
            entry = self._pending.pop(approval_id, None)
            return bool(entry.get("approved")) if entry else False

    def take_and_execute(self, approval_id: str) -> Optional[Any]:
        """弹出已批准的审批条目并执行其 action (审批回调通过后由后台线程调用)"""
        with self._lock:
            entry = self._pending.pop(approval_id, None)
        if not entry:
            logger.warning("[approval] %s not found when executing", approval_id)
            return None
        if not entry.get("approved"):
            logger.info("[approval] %s not approved, skip execution", approval_id)
            return None
        if time.time() - entry["created_at"] > APPROVAL_TIMEOUT:
            logger.info("[approval] %s expired before execution", approval_id)
            return None
        logger.info("[approval] executing approved action: %s", entry["action_name"])
        return entry["action_func"](*entry["action_args"], **entry["action_kwargs"])

    def get_pending(self, approval_id: str) -> Optional[dict]:
        """查询审批状态"""
        with self._lock:
            entry = self._pending.get(approval_id)
        if entry and time.time() - entry["created_at"] > APPROVAL_TIMEOUT:
            self._pending.pop(approval_id, None)
            return None
        return entry

    def cleanup_expired(self):
        """清理过期审批"""
        now = time.time()
        with self._lock:
            expired = [
                k for k, v in self._pending.items()
                if now - v["created_at"] > APPROVAL_TIMEOUT
            ]
            for k in expired:
                del self._pending[k]
        if expired:
            logger.info("[approval] cleaned %d expired entries", len(expired))

    @property
    def pending_count(self) -> int:
        return len(self._pending)


# 全局单例
approval_manager = ApprovalManager()

# 需要审批的技能标记 (默认留空: 高危动作以指令关键词识别为主,
# 避免库存预警等正常查询被误拦截)
REQUIRES_APPROVAL_SKILLS = set()

# 高危动作关键词: 用户指令包含这些词时, 对应技能执行前需人工审批 (如降价)
HIGH_RISK_KEYWORDS = [
    "降价", "减价", "调价", "改价", "打折", "折扣",
    "下架", "删除商品", "清仓", "停售",
    # L4 补充: 涨价/发券方向同样属于高风险动作
    "调高", "涨价", "提价", "发券",
]

# 审批门总开关（默认关闭）；设为 true 时高危动作执行前需人工批准
APPROVAL_ENABLED = os.getenv("APPROVAL_ENABLED", "false").lower() == "true"

# 审批操作者白名单 (飞书 open_id, 逗号分隔): 仅名单内用户可以批准/拒绝/点选决策方案
APPROVAL_OPERATORS = {
    o.strip()
    for o in os.getenv("APPROVAL_OPERATORS", "").split(",")
    if o.strip()
}


def is_authorized_approver(open_id: str) -> bool:
    """判断操作者是否具备审批权限; 未配置白名单时默认拒绝 (fail-closed)"""
    return bool(APPROVAL_OPERATORS) and open_id in APPROVAL_OPERATORS


def should_gate(skill_name: str, user_input: str = "") -> bool:
    """判断某次执行是否需要审批门: 技能在标记集合中, 或指令含高危动作关键词"""
    if not APPROVAL_ENABLED:
        return False
    if skill_name in REQUIRES_APPROVAL_SKILLS:
        return True
    if user_input:
        return any(kw in user_input for kw in HIGH_RISK_KEYWORDS)
    return False


def gate_and_wait(skill_name: str, conversation_id: str = "", description: str = "", timeout: float = None) -> bool:
    """创建审批并阻塞等待人工决策。返回 True=批准 / False=拒绝或超时。
    外部通过 POST /approval/{id}/resolve 解决；飞书卡片按钮应调用该回调。"""
    aid = approval_manager.create_approval(
        action_name=skill_name,
        action_func=lambda: None,
        conversation_id=conversation_id,
        description=description or skill_name,
    )
    logger.warning(
        "[approval] GATE skill=%s approval_id=%s waiting for human decision (timeout=%ss)",
        skill_name, aid, timeout if timeout is not None else APPROVAL_TIMEOUT,
    )
    approved = approval_manager.wait_decision(aid, timeout)
    logger.warning(
        "[approval] GATE skill=%s approval_id=%s decision=%s",
        skill_name, aid, "approved" if approved else "rejected/timeout",
    )
    return approved