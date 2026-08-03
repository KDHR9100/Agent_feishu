"""L4 市场哨兵触发引擎: APScheduler 定时轮询竞品 Top N, 阈值触发 MARKET_ALERT

触发规则 (阈值见 app/config.py SENTINEL_CONFIG):
- 竞品价格波动 > 3%  -> MARKET_ALERT (type=price)
- 差评率突增 > 5%(绝对值) -> MARKET_ALERT (type=negative_review)
"""
import asyncio
import logging
from typing import Dict, Optional

from app.config import SENTINEL_CONFIG
from .crawler_base import BaseCrawler, MockTmallCrawler, mock_market
from .event_bus import event_bus, MARKET_ALERT

logger = logging.getLogger("sentinel.trigger_engine")


class MarketSentinel:
    """市场哨兵: 周期性抓取竞品价格/差评率, 与基线对比后发布告警事件"""

    def __init__(self, crawler: Optional[BaseCrawler] = None, bus=None, store=None):
        self.crawler = crawler or MockTmallCrawler()
        self.bus = bus or event_bus
        self.store = store or mock_market
        # 基线数据: {product_name: {"price": x, "negative_rate": y}}
        self.baseline: Dict[str, Dict] = {}
        self._scheduler = None
        self.check_count = 0
        self.alert_count = 0

    # ---------- 核心检测逻辑 (可被测试直接调用) ----------
    def check_once(self, top_n: Optional[int] = None):
        """执行一轮巡检: 抓取 Top N 竞品数据并与基线比对, 返回本轮告警列表"""
        top_n = top_n or SENTINEL_CONFIG["top_n"]
        products = self.store.top_products(top_n)
        try:
            results = asyncio.run(self._fetch_all(products))
        except RuntimeError:
            # 已存在运行中的事件循环 (如 FastAPI 协程/测试客户端内):
            # 同线程无法再跑第二个循环, 改在独立线程中执行
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                results = pool.submit(asyncio.run, self._fetch_all(products)).result()
        return self._compare_and_alert(results)

    async def _fetch_all(self, products):
        """并发抓取所有竞品的价格与差评率"""
        results = []
        for name in products:
            url = "https://mock.%s.com/item/%s" % (self.crawler.platform, name)
            price_info = await self.crawler.fetch_price(url)
            review_info = await self.crawler.fetch_reviews(name)
            results.append({
                "product": name,
                "price": price_info.get("price"),
                "negative_rate": review_info.get("negative_rate"),
            })
        return results

    def _compare_and_alert(self, results):
        alerts = []
        price_th = SENTINEL_CONFIG["price_change_threshold"]
        neg_th = SENTINEL_CONFIG["negative_review_threshold"]

        for item in results:
            name = item["product"]
            price = item.get("price")
            neg_rate = item.get("negative_rate")
            if price is None and neg_rate is None:
                continue

            base = self.baseline.get(name)
            if base is None:
                # 首次巡检: 建立基线, 不告警
                self.baseline[name] = {"price": price, "negative_rate": neg_rate}
                logger.info("[sentinel] baseline set for %s: price=%s neg=%s", name, price, neg_rate)
                continue

            # ---- 价格波动检测 ----
            old_price = base.get("price")
            if price is not None and old_price:
                change_pct = (price - old_price) / old_price
                if abs(change_pct) >= price_th:
                    direction = "降价" if change_pct < 0 else "涨价"
                    alert = {
                        "type": "price",
                        "product": name,
                        "old_price": old_price,
                        "new_price": price,
                        "change_pct": round(change_pct, 4),
                        "message": "[ALERT] 竞品 %s %s %d%%" % (name, direction, round(abs(change_pct) * 100)),
                    }
                    alerts.append(alert)
                    self.alert_count += 1
                    # Checkpoint 1 要求: 终端可见 [ALERT] 竞品 iPhone 15 降价 4%
                    print(alert["message"])
                    logger.warning(alert["message"])
                    self.bus.publish(MARKET_ALERT, alert)

            # ---- 差评率突增检测 ----
            old_neg = base.get("negative_rate")
            if neg_rate is not None and old_neg is not None:
                neg_delta = neg_rate - old_neg
                if neg_delta >= neg_th:
                    alert = {
                        "type": "negative_review",
                        "product": name,
                        "old_negative_rate": old_neg,
                        "new_negative_rate": neg_rate,
                        "change": round(neg_delta, 4),
                        "message": "[ALERT] 竞品 %s 差评率突增 %.1f%%" % (name, neg_delta * 100),
                    }
                    alerts.append(alert)
                    self.alert_count += 1
                    print(alert["message"])
                    logger.warning(alert["message"])
                    self.bus.publish(MARKET_ALERT, alert)

            # 更新基线
            self.baseline[name] = {"price": price, "negative_rate": neg_rate}

        self.check_count += 1
        logger.info("[sentinel] check #%d done, %d products, %d alerts", self.check_count, len(results), len(alerts))
        return alerts

    # ---------- 调度 ----------
    def start(self):
        """启动 APScheduler, 每 SENTINEL_CONFIG.poll_interval_minutes 分钟轮询一次"""
        if self._scheduler is not None:
            logger.warning("[sentinel] already started")
            return
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.interval import IntervalTrigger

        self._scheduler = BackgroundScheduler()
        interval = SENTINEL_CONFIG["poll_interval_minutes"]
        self._scheduler.add_job(
            self.check_once,
            trigger=IntervalTrigger(minutes=interval),
            id="sentinel_market_poll",
            name="市场哨兵竞品轮询",
        )
        self._scheduler.start()
        # 启动时立即建立基线, 保证下一轮开始有对比数据
        try:
            self.check_once()
        except Exception as e:
            logger.error("[sentinel] initial baseline check failed: %s", e)
        logger.info("[sentinel] started, poll every %d minutes", interval)

    def stop(self):
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            logger.info("[sentinel] stopped")

    def get_status(self):
        return {
            "running": self._scheduler.running if self._scheduler else False,
            "check_count": self.check_count,
            "alert_count": self.alert_count,
            "baseline_products": list(self.baseline.keys()),
        }


# 全局单例
sentinel = MarketSentinel()
