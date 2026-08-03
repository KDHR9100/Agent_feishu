# -*- coding: utf-8 -*-
"""L4 店铺平台适配层 (物理执行层)

安全红线: 所有 StoreAPI 默认启用 MockBackend, 仅当环境变量 EXECUTOR_REAL_MODE=true
且显式完成对应平台 SDK 接入后才可能走真实链路; 当前真实适配器方法全部预留抛错,
防止误操作正式环境。
"""
import logging
import time
import uuid
from abc import ABC, abstractmethod

from app.config import EXECUTOR_REAL_MODE

logger = logging.getLogger("executor.adapter")


class StoreAPI(ABC):
    """店铺后台抽象接口: 预留天猫/Shopify/抖音小店 SDK 接入"""

    platform = "abstract"

    @abstractmethod
    def get_price(self, product_id: str) -> float:
        """查询商品当前价格"""

    @abstractmethod
    def update_price(self, product_id: str, new_price: float) -> dict:
        """修改商品价格, 返回执行回执 dict"""

    @abstractmethod
    def batch_send_coupons(self, coupon_params: dict) -> dict:
        """批量发券"""

    @abstractmethod
    def delist_product(self, product_id: str) -> dict:
        """下架商品"""

    @abstractmethod
    def relist_product(self, product_id: str) -> dict:
        """重新上架 (回滚用)"""


class MockStoreAPI(StoreAPI):
    """Mock 后端: 仅打印日志 + 维护内存态价格/状态, 绝不触碰真实店铺"""

    platform = "mock"

    def __init__(self):
        self._prices = {"default_hot_item": 99.0}
        self._status = {"default_hot_item": "on_sale"}
        self._receipt_seq = 0

    def _receipt(self, message, **extra):
        self._receipt_seq += 1
        receipt = {
            "success": True,
            "receipt_id": "mock-%s-%d" % (uuid.uuid4().hex[:8], self._receipt_seq),
            "message": message,
            "platform": self.platform,
            "executed_at": time.time(),
        }
        receipt.update(extra)
        print("[MockStoreAPI] %s" % message)
        logger.info("[MockStoreAPI] %s | extra=%s", message, extra)
        return receipt

    def get_price(self, product_id: str) -> float:
        return self._prices.get(product_id, 99.0)

    def update_price(self, product_id: str, new_price: float) -> dict:
        if new_price is None or float(new_price) <= 0:
            return {"success": False, "message": "非法价格: %s" % new_price}
        old_price = self._prices.get(product_id, 99.0)
        self._prices[product_id] = float(new_price)
        return self._receipt(
            "模拟修改价格成功: %s %.2f -> %.2f" % (product_id, old_price, float(new_price)),
            product_id=product_id, old_price=old_price, new_price=float(new_price),
        )

    def batch_send_coupons(self, coupon_params: dict) -> dict:
        return self._receipt(
            "模拟批量发券成功: %s" % (coupon_params or {}),
            coupon_params=coupon_params,
        )

    def delist_product(self, product_id: str) -> dict:
        old_status = self._status.get(product_id, "on_sale")
        self._status[product_id] = "delisted"
        return self._receipt(
            "模拟下架商品成功: %s" % product_id,
            product_id=product_id, old_status=old_status,
        )

    def relist_product(self, product_id: str) -> dict:
        self._status[product_id] = "on_sale"
        return self._receipt(
            "模拟重新上架成功: %s" % product_id,
            product_id=product_id,
        )


class TmallStoreAPI(StoreAPI):
    """天猫开放平台 SDK 接入预留位 (TOP SDK), 未接入前禁止真实操作"""

    platform = "tmall"

    def _not_implemented(self):
        raise NotImplementedError(
            "天猫 SDK 尚未接入: 请配置 TOP_APP_KEY/TOP_APP_SECRET 并完成授权后才可执行真实操作"
        )

    def get_price(self, product_id):
        self._not_implemented()

    def update_price(self, product_id, new_price):
        self._not_implemented()

    def batch_send_coupons(self, coupon_params):
        self._not_implemented()

    def delist_product(self, product_id):
        self._not_implemented()

    def relist_product(self, product_id):
        self._not_implemented()


class ShopifyStoreAPI(StoreAPI):
    """Shopify Admin API 接入预留位"""

    platform = "shopify"

    def _not_implemented(self):
        raise NotImplementedError("Shopify Admin API 尚未接入")

    get_price = update_price = batch_send_coupons = _not_implemented
    delist_product = relist_product = _not_implemented


class DouyinStoreAPI(StoreAPI):
    """抖音小店开放平台接入预留位"""

    platform = "douyin"

    def _not_implemented(self):
        raise NotImplementedError("抖音小店 SDK 尚未接入")

    get_price = update_price = batch_send_coupons = _not_implemented
    delist_product = relist_product = _not_implemented


_REAL_ADAPTER_MAP = {
    "tmall": TmallStoreAPI,
    "shopify": ShopifyStoreAPI,
    "douyin": DouyinStoreAPI,
}

_mock_singleton = None


def get_store_api() -> StoreAPI:
    """工厂: 默认 Mock; 仅当 EXECUTOR_REAL_MODE=true 时按 STORE_PLATFORM 选择真实适配器

    注意: 真实适配器当前全部为预留实现, 调用即抛 NotImplementedError, 双重保险防误操作。
    """
    import os

    global _mock_singleton
    if EXECUTOR_REAL_MODE:
        platform = os.getenv("STORE_PLATFORM", "tmall").lower()
        cls = _REAL_ADAPTER_MAP.get(platform)
        if cls is None:
            logger.error("[adapter] unknown STORE_PLATFORM=%s, fallback to Mock", platform)
        else:
            logger.warning("[adapter] EXECUTOR_REAL_MODE=true, using %s adapter", platform)
            return cls()
    if _mock_singleton is None:
        _mock_singleton = MockStoreAPI()
    return _mock_singleton
