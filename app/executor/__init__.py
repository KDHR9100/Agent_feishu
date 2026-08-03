# -*- coding: utf-8 -*-
"""L4 店铺后台执行闭环 (物理执行层)

组件:
- platform_adapter: StoreAPI 抽象 + MockStoreAPI 默认后端 (EXECUTOR_REAL_MODE 开关)
- action_verifier: 三类高风险动作强制飞书卡片审批 (复用 ApprovalManager)
- rollback_manager: 记录 action_id 与旧值, 1 小时未确认自动回滚
"""
from app.executor.platform_adapter import (
    DouyinStoreAPI,
    MockStoreAPI,
    ShopifyStoreAPI,
    StoreAPI,
    TmallStoreAPI,
    get_store_api,
)
from app.executor.rollback_manager import RollbackManager, get_rollback_manager
from app.executor.action_verifier import (
    HIGH_RISK_ACTIONS,
    ActionVerifier,
    get_action_verifier,
)

__all__ = [
    "StoreAPI", "MockStoreAPI", "TmallStoreAPI", "ShopifyStoreAPI",
    "DouyinStoreAPI", "get_store_api",
    "RollbackManager", "get_rollback_manager",
    "ActionVerifier", "get_action_verifier", "HIGH_RISK_ACTIONS",
]
