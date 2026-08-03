"""高危操作动作日志 (SQLite, 标准库实现)

记录审批的创建/批准/拒绝/执行结果, 便于审计追踪。
与主库共用 DATABASE_URL 指向的 SQLite 文件。
"""
import logging
import os
import sqlite3
import threading
from datetime import datetime

logger = logging.getLogger("action_log")

_DB_PATH = os.getenv("DATABASE_URL", "sqlite:///./feishu_agent.db").replace(
    "sqlite:///", ""
)

_lock = threading.Lock()
_initialized = False


def _ensure_table(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS action_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            approval_id TEXT,
            skill_name TEXT,
            description TEXT,
            decision TEXT,
            operator TEXT,
            conversation_id TEXT,
            result TEXT
        )"""
    )


def log_action(
    approval_id="",
    skill_name="",
    description="",
    decision="",
    operator="",
    conversation_id="",
    result="",
):
    """写一条动作日志 (失败不影响主流程)"""
    global _initialized
    try:
        with _lock:
            conn = sqlite3.connect(_DB_PATH, timeout=5)
            try:
                if not _initialized:
                    _ensure_table(conn)
                    _initialized = True
                conn.execute(
                    "INSERT INTO action_log "
                    "(ts, approval_id, skill_name, description, decision, operator, conversation_id, result) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (
                        datetime.now().isoformat(timespec="seconds"),
                        approval_id,
                        skill_name,
                        (description or "")[:500],
                        decision,
                        operator,
                        conversation_id,
                        (result or "")[:500],
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        logger.info(
            "[action_log] approval=%s skill=%s decision=%s",
            approval_id, skill_name, decision,
        )
    except Exception as e:
        logger.warning("[action_log] write failed: %s", e)


def recent_actions(limit=20):
    """查询最近的动作日志"""
    try:
        conn = sqlite3.connect(_DB_PATH, timeout=5)
        try:
            _ensure_table(conn)
            cur = conn.execute(
                "SELECT ts, approval_id, skill_name, description, decision, operator, result "
                "FROM action_log ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            cols = ["ts", "approval_id", "skill_name", "description", "decision", "operator", "result"]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        finally:
            conn.close()
    except Exception as e:
        logger.warning("[action_log] query failed: %s", e)
        return []
