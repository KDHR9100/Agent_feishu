"""工单管理工具 - 为客服支持技能提供工单 CRUD 操作

基于 SQLite 存储工单数据，提供：
- 创建工单（create_ticket）
- 按订单号查询（query_order）
- 按手机号查询（query_by_phone）
- 按工单 ID 查询（get_ticket）
- 更新工单状态（update_status）

使用方式：
    from app.tools.ticket_tool import ticket_tool
    result = ticket_tool.query_order("ORD001")
    ticket = ticket_tool.create_ticket("ORD001", "退货", "商品有瑕疵")
"""
import logging
import sqlite3
from typing import Dict, Any
from datetime import datetime

logger = logging.getLogger("ticket_tool")


class TicketTool:
    """工单管理工具 - SQLite 存储"""

    def __init__(self, db_path: str = "tickets.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """初始化工单表"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tickets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT,
                    phone TEXT,
                    category TEXT DEFAULT 'general',
                    description TEXT,
                    status TEXT DEFAULT 'open',
                    priority TEXT DEFAULT 'normal',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
            conn.close()
            logger.info("[ticket_tool] Database initialized: %s", self.db_path)
        except Exception as e:
            logger.error("[ticket_tool] DB init error: %s", e)

    def create_ticket(
        self,
        order_id: str = "",
        category: str = "general",
        description: str = "",
        phone: str = "",
        priority: str = "normal",
    ) -> Dict[str, Any]:
        """创建工单

        Args:
            order_id: 关联订单号
            category: 工单分类（退货/换货/投诉/咨询等）
            description: 问题描述
            phone: 用户手机号
            priority: 优先级（low/normal/high/urgent）

        Returns:
            包含工单 ID 和创建结果
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO tickets
                   (order_id, phone, category, description, priority)
                   VALUES (?, ?, ?, ?, ?)""",
                (order_id, phone, category, description, priority),
            )
            conn.commit()
            ticket_id = cursor.lastrowid
            conn.close()
            logger.info(
                "[ticket_tool] Created ticket #%d, order=%s, category=%s",
                ticket_id, order_id, category,
            )
            return {
                "success": True,
                "ticket_id": ticket_id,
                "order_id": order_id,
                "category": category,
                "status": "open",
            }
        except Exception as e:
            logger.error("[ticket_tool] Create ticket error: %s", e)
            return {"success": False, "error": str(e)}

    def query_order(self, order_id: str) -> Dict[str, Any]:
        """按订单号查询工单

        Args:
            order_id: 订单号

        Returns:
            该订单关联的所有工单
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM tickets WHERE order_id = ? ORDER BY created_at DESC",
                (order_id,),
            )
            rows = cursor.fetchall()
            conn.close()

            if rows:
                tickets = [dict(row) for row in rows]
                logger.info(
                    "[ticket_tool] Found %d tickets for order %s",
                    len(tickets), order_id,
                )
                return {
                    "order_id": order_id,
                    "tickets": tickets,
                    "count": len(tickets),
                }
            else:
                return {
                    "order_id": order_id,
                    "tickets": [],
                    "count": 0,
                    "note": "No tickets found for this order",
                }
        except Exception as e:
            logger.error("[ticket_tool] Query order error: %s", e)
            return {"error": str(e)}

    def query_by_phone(self, phone: str) -> Dict[str, Any]:
        """按手机号查询工单

        Args:
            phone: 用户手机号

        Returns:
            该手机号关联的所有工单
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM tickets WHERE phone = ? ORDER BY created_at DESC",
                (phone,),
            )
            rows = cursor.fetchall()
            conn.close()

            if rows:
                tickets = [dict(row) for row in rows]
                return {
                    "phone": phone,
                    "tickets": tickets,
                    "count": len(tickets),
                }
            else:
                return {
                    "phone": phone,
                    "tickets": [],
                    "count": 0,
                    "note": "No tickets found for this phone",
                }
        except Exception as e:
            logger.error("[ticket_tool] Query by phone error: %s", e)
            return {"error": str(e)}

    def get_ticket(self, ticket_id: int) -> Dict[str, Any]:
        """按工单 ID 查询

        Args:
            ticket_id: 工单 ID

        Returns:
            工单详情
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
            row = cursor.fetchone()
            conn.close()

            if row:
                return {"success": True, "ticket": dict(row)}
            else:
                return {"success": False, "error": "Ticket not found"}
        except Exception as e:
            logger.error("[ticket_tool] Get ticket error: %s", e)
            return {"success": False, "error": str(e)}

    def update_status(
        self, ticket_id: int, status: str
    ) -> Dict[str, Any]:
        """更新工单状态

        Args:
            ticket_id: 工单 ID
            status: 新状态 (open/in_progress/resolved/closed)

        Returns:
            更新结果
        """
        valid_statuses = {"open", "in_progress", "resolved", "closed"}
        if status not in valid_statuses:
            return {
                "success": False,
                "error": f"Invalid status. Must be one of: {valid_statuses}",
            }
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE tickets SET status = ?, updated_at = ?
                   WHERE id = ?""",
                (status, datetime.utcnow().isoformat(), ticket_id),
            )
            conn.commit()
            affected = cursor.rowcount
            conn.close()

            if affected > 0:
                logger.info(
                    "[ticket_tool] Updated ticket #%d status to %s",
                    ticket_id, status,
                )
                return {"success": True, "ticket_id": ticket_id, "status": status}
            else:
                return {"success": False, "error": "Ticket not found"}
        except Exception as e:
            logger.error("[ticket_tool] Update status error: %s", e)
            return {"success": False, "error": str(e)}


ticket_tool = TicketTool()
