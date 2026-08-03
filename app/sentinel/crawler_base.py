"""L4 异步爬虫基类 (httpx + parsel, 可选 curl_cffi 浏览器指纹伪装)

现状说明:
- 2026 年主流电商平台(天猫/京东/抖音)均有强反爬, 真实抓取需 curl_cffi 模拟浏览器指纹
- 本期全部平台走 Mock 公开数据接口 (MockMarketStore), 不发起真实网络请求
- curl_cffi / parsel 均为可选导入, 缺失时自动降级, 不阻塞主流程
"""
import logging
from typing import Dict, Optional
from urllib.parse import unquote

logger = logging.getLogger("sentinel.crawler")

# ===== 可选依赖: curl_cffi (浏览器指纹伪装), 装不上自动降级 httpx =====
try:
    from curl_cffi.requests import AsyncSession as _CurlCffiSession
    HAS_CURL_CFFI = True
except ImportError:  # pragma: no cover - 取决于运行环境
    HAS_CURL_CFFI = False

try:
    import httpx
    HAS_HTTPX = True
except ImportError:  # pragma: no cover
    HAS_HTTPX = False

try:
    from parsel import Selector
    HAS_PARSEL = True
except ImportError:  # pragma: no cover
    HAS_PARSEL = False


class BaseCrawler:
    """异步爬虫基类: 子类实现 fetch_price(url) 与 fetch_reviews(keyword)"""

    platform = "base"
    # curl_cffi 支持的浏览器指纹标识
    impersonate = "chrome120"
    timeout = 10.0

    async def fetch_page(self, url: str) -> str:
        """抓取页面 HTML: 优先 curl_cffi 指纹伪装, 降级 httpx"""
        if HAS_CURL_CFFI:
            async with _CurlCffiSession(impersonate=self.impersonate) as session:
                resp = await session.get(url, timeout=self.timeout)
                resp.raise_for_status()
                return resp.text
        if HAS_HTTPX:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    url, headers={"User-Agent": "Mozilla/5.0 (compatible; SentinelBot)"}
                )
                resp.raise_for_status()
                return resp.text
        raise RuntimeError("no HTTP backend available (need curl_cffi or httpx)")

    @staticmethod
    def parse_price_from_html(html: str, css_selector: str) -> Optional[float]:
        """从 HTML 解析价格 (parsel 可选; 真实平台接入时使用)"""
        if not HAS_PARSEL:
            logger.warning("parsel not installed, skip html parsing")
            return None
        sel = Selector(text=html)
        raw = sel.css(css_selector + "::text").get()
        if raw is None:
            return None
        digits = "".join(ch for ch in raw if ch.isdigit() or ch == ".")
        try:
            return float(digits)
        except ValueError:
            return None

    async def fetch_price(self, url: str) -> Dict:
        raise NotImplementedError

    async def fetch_reviews(self, keyword: str) -> Dict:
        raise NotImplementedError


# ============================================================
# Mock 市场数据源: 模拟天猫/京东/抖音公开数据接口
# 数据可被外部修改 (set_price/set_negative_rate), 供测试注入波动场景
# ============================================================
_DEFAULT_COMPETITORS = [
    {"name": "iPhone 15", "price": 5999.0, "negative_rate": 0.02},
    {"name": "小米14", "price": 3999.0, "negative_rate": 0.03},
    {"name": "华为Mate60", "price": 5499.0, "negative_rate": 0.02},
    {"name": "荣耀Magic6", "price": 3699.0, "negative_rate": 0.04},
    {"name": "vivo X100", "price": 3599.0, "negative_rate": 0.03},
    {"name": "OPPO Find X7", "price": 3799.0, "negative_rate": 0.03},
    {"name": "三星S24", "price": 4999.0, "negative_rate": 0.05},
    {"name": "一加12", "price": 4299.0, "negative_rate": 0.04},
    {"name": "真我GT5 Pro", "price": 3299.0, "negative_rate": 0.06},
    {"name": "红米K70 Pro", "price": 2999.0, "negative_rate": 0.05},
]


class MockMarketStore:
    """内存市场数据源 (竞品 Top N 价格 + 差评率)"""

    def __init__(self, competitors=None):
        self._data = {}
        for item in competitors or _DEFAULT_COMPETITORS:
            self._data[item["name"]] = {
                "price": item["price"],
                "negative_rate": item["negative_rate"],
            }

    def top_products(self, n=10):
        return list(self._data.keys())[:n]

    def get(self, name: str) -> Optional[Dict]:
        return self._data.get(name)

    def set_price(self, name: str, price: float):
        """测试注入: 修改竞品价格"""
        self._data.setdefault(name, {"price": price, "negative_rate": 0.02})
        self._data[name]["price"] = price

    def set_negative_rate(self, name: str, rate: float):
        """测试注入: 修改差评率"""
        self._data.setdefault(name, {"price": 100.0, "negative_rate": rate})
        self._data[name]["negative_rate"] = rate


# 全局 Mock 数据源
mock_market = MockMarketStore()


def _name_from_url(url: str) -> str:
    """从 Mock URL 中还原商品名: https://mock.tmall.com/item/<name>"""
    return unquote(url.rstrip("/").rsplit("/", 1)[-1])


class MockTmallCrawler(BaseCrawler):
    """天猫 Mock 数据接口 (不发真实请求); 可注入独立 store 供测试隔离"""
    platform = "tmall"

    def __init__(self, store: Optional[MockMarketStore] = None):
        self.store = store or mock_market

    async def fetch_price(self, url: str) -> Dict:
        name = _name_from_url(url)
        item = self.store.get(name)
        if not item:
            return {"url": url, "platform": self.platform, "price": None, "error": "not_found"}
        return {"url": url, "platform": self.platform, "product": name, "price": item["price"]}

    async def fetch_reviews(self, keyword: str) -> Dict:
        item = self.store.get(keyword)
        if not item:
            return {"keyword": keyword, "platform": self.platform, "negative_rate": None, "error": "not_found"}
        return {"keyword": keyword, "platform": self.platform, "negative_rate": item["negative_rate"]}


class MockJdCrawler(MockTmallCrawler):
    """京东 Mock 数据接口"""
    platform = "jd"


class MockDouyinCrawler(MockTmallCrawler):
    """抖音小店 Mock 数据接口"""
    platform = "douyin"
