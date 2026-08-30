# -*- coding: utf-8 -*-
"""L4 动作校验器: 高风险动作执行前强制飞书卡片审批

链路: verify_and_execute(execution_request)
  - update_price (调价): 审批卡片 -> 人工点击批准 -> 登记调价决策 + 推送
    手动执行引导。定位边界: 多数电商开放平台不覆盖网页端改价, 且此前 Mock
    适配器"改内存价格"会制造"已改价"的虚假闭环 —— 实际改价由运营在平台
    商家后台手动完成, Agent 负责 模拟验证 + 人工审批 + 决策登记 + 执行引导。
  - 其余高风险动作(batch_send_coupons/delist_product):
      审批卡片 -> 人工批准 -> 经 store adapter 执行 (默认 Mock) -> 登记回滚窗口
  - 其余动作: 直接经 store adapter 执行 (默认 Mock)
"""
import logging
import time
import uuid

from app.utils.action_log import log_action

logger = logging.getLogger("executor.verifier")

# 三类高风险动作: 执行前必须人工审批
HIGH_RISK_ACTIONS = {"update_price", "batch_send_coupons", "delist_product"}


class ActionVerifier:
    def __init__(self, store_api=None, rollback_manager=None, approvals=None):
        from app.executor.platform_adapter import get_store_api
        from app.executor.rollback_manager import get_rollback_manager
        from app.utils.approval import approval_manager

        self.store = store_api or get_store_api()
        self.rollback = rollback_manager or get_rollback_manager()
        self.approvals = approvals or approval_manager

    # ---------- 入口 ----------
    def verify_and_execute(self, execution_request, conversation_id="",
                           skill_name="", user_input=""):
        execution_request = execution_request or {}
        action = execution_request.get("action", "")
        params = execution_request.get("params") or {}
        description = execution_request.get("description") or action
        logger.info(
            "[verifier] action=%s params=%s conversation=%s",
            action, params, conversation_id,
        )
        if action in HIGH_RISK_ACTIONS:
            return self._request_approval(
                action, params, description, conversation_id, skill_name)
        receipt = self._execute(action, params, conversation_id)
        return {"type": "executed", "data": receipt}

    # ---------- 审批 ----------
    def _request_approval(self, action, params, description, conversation_id, skill_name):
        ctx = {"approval_id": None}

        def on_approved():
            # 审批卡片点击批准后由 take_and_execute 在后台线程调用
            return self._execute_after_approval(
                action, params, description, conversation_id, skill_name,
                ctx["approval_id"])

        aid = self.approvals.create_approval(
            action_name=action,
            action_func=on_approved,
            conversation_id=conversation_id,
            description=description,
        )
        ctx["approval_id"] = aid
        try:
            log_action(approval_id=aid, skill_name=skill_name,
                       description=description[:100], decision="pending",
                       conversation_id=conversation_id)
        except Exception as e:
            logger.warning("[verifier] log_action failed: %s", e)
        logger.warning(
            "[verifier] HIGH-RISK action=%s blocked, approval_id=%s, "
            "waiting for human (5min timeout)", action, aid,
        )
        return {
            "type": "approval_required",
            "data": {
                "approval_id": aid,
                "skill": skill_name,
                "description": description,
                "response": "⏳ 该操作属于高风险动作（%s），需要人工审批。"
                            "已发送审批卡片，请在卡片上点击【批准并执行】或【拒绝】；"
                            "5 分钟内无人处理将自动放弃并记录日志。" % action,
            },
        }

    # ---------- 执行 ----------
    def _register_price_change_decision(self, params):
        """调价决策登记: 不触碰店铺数据, 产出决策回执 + 手动执行引导

        审批卡片上的价格对审批人展示的是 params 里的 old/new_price,
        登记口径必须与之一致(取 params 优先, store 现价仅作缺失兜底)。
        """
        pid = params.get("product_id")
        new_price = float(params.get("new_price") or 0)
        if new_price <= 0:
            # 非法价格在登记层显式拒绝(旧链路由 store adapter 拦截, 重定位后职责前移)
            return {"success": False, "message": "非法价格: %s" % params.get("new_price")}
        old_price = float(params.get("old_price") or self.store.get_price(pid) or 0)
        return {
            "success": True,
            "receipt_id": "decision-%s" % uuid.uuid4().hex[:8],
            "message": "调价决策已登记: %s %.2f -> %.2f 元" % (pid, old_price, new_price),
            "product_id": pid,
            "old_price": old_price,
            "new_price": new_price,
            "platform": "manual",
            "executed_at": time.time(),
            "manual_guide": "请在电商平台商家后台手动完成改价；"
                            "改价完成后告诉我，可以基于新价格复测损益影响。",
        }

    def _execute(self, action, params, conversation_id=""):
        receipt = {"success": False, "message": "unsupported action"}
        if action == "update_price":
            receipt = self._register_price_change_decision(params)
        elif action == "batch_send_coupons":
            receipt = self.store.batch_send_coupons(params)
            if receipt.get("success"):
                aid = self.rollback.record(
                    action, params, {}, conversation_id=conversation_id,
                    rollbackable=False)  # 已发出的券不可自动回滚
                receipt["action_id"] = aid
        elif action == "delist_product":
            pid = params.get("product_id")
            receipt = self.store.delist_product(pid)
            if receipt.get("success"):
                aid = self.rollback.record(
                    action, params, {"old_status": "on_sale"},
                    conversation_id=conversation_id)
                receipt["action_id"] = aid
        else:
            logger.warning("[verifier] unsupported action=%s", action)

        receipt["action"] = action
        if action == "update_price":
            # 决策登记语义: 无回滚窗口, 最终状态以商家后台实际改价为准
            receipt["post_status"] = (
                "registered" if receipt.get("success") else "failed")
        else:
            receipt["post_status"] = (
                "awaiting_confirmation" if receipt.get("success") else "failed")
        if receipt.get("success"):
            if action == "update_price":
                print("[executor] 调价决策已登记 | product=%s | %.2f -> %.2f | receipt_id=%s"
                      % (params.get("product_id"), receipt.get("old_price", 0.0),
                         receipt.get("new_price", 0.0), receipt.get("receipt_id")))
            else:
                mode = "Mock" if getattr(self.store, "platform", "") == "mock" else "真实平台"
                print("[executor] %s 执行成功 | action=%s | receipt_id=%s"
                      % (mode, action, receipt.get("receipt_id")))
        return receipt

    def _execute_after_approval(self, action, params, description,
                                conversation_id, skill_name, approval_id):
        receipt = self._execute(action, params, conversation_id)
        # 执行后回执: 写动作日志 + 推送飞书
        try:
            log_action(approval_id=approval_id or "", skill_name=skill_name,
                       description=description[:100], decision="executed",
                       conversation_id=conversation_id,
                       result=str(receipt.get("message"))[:200])
        except Exception as e:
            logger.warning("[verifier] log_action failed: %s", e)
        self._push_receipt_message(conversation_id, receipt)
        return receipt

    def _push_receipt_message(self, conversation_id, receipt):
        if not conversation_id:
            return
        try:
            from app.tools.feishu_tool import feishu_tool
            lines = [
                "✅ 审批处理回执：%s" % receipt.get("message", ""),
                "动作 ID：%s" % (receipt.get("action_id") or receipt.get("receipt_id") or "-"),
            ]
            if receipt.get("rollback_note"):
                lines.append("⚠️ %s" % receipt["rollback_note"])
                lines.append("如确认无误，请在 1 小时内回复确认完成，否则将自动回滚。")
            if receipt.get("manual_guide"):
                lines.append("📌 %s" % receipt["manual_guide"])
            feishu_tool.send_message(conversation_id, "\n".join(lines))
        except Exception as e:
            logger.warning("[verifier] push receipt to feishu failed: %s", e)


# 懒加载单例 (避免 import 期触发 store/线程初始化)
_instance = None


def get_action_verifier() -> ActionVerifier:
    global _instance
    if _instance is None:
        _instance = ActionVerifier()
    return _instance
