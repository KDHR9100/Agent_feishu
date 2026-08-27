"""CrossLister HTTP 客户端

CrossLister 是独立运行的 FastAPI 微服务(默认端口 8080), 提供基于商品图片的
多模态 Listing 生成能力: 视觉分析 -> 平台规则 RAG -> 合规审核 -> 多语言 Listing。

本客户端通过 HTTP 调用该服务, 不共享进程:
- 服务地址: 环境变量 CROSSLISTER_URL, 默认 http://localhost:8080
- 超时默认 180s (listing 生成涉及多步模型调用, 实测约 50-60s),
  可通过环境变量 CROSSLISTER_TIMEOUT 调整
- 所有网络/解析错误均捕获为 error dict, 不向上抛异常
"""
import logging
import os
from typing import Dict, List, Optional

import httpx

logger = logging.getLogger("crosslister_client")

# listing 生成涉及视觉分析 + 多步 LLM 调用, 需要较长超时
# (真实 API 模式实测约 50-60s, 多图片/慢模型时可能更久)
_REQUEST_TIMEOUT = float(os.environ.get("CROSSLISTER_TIMEOUT", "180"))
# 健康检查是轻量请求, 用短超时快速失败
_HEALTH_TIMEOUT = 10.0

# 支持的图片扩展名 -> MIME 类型映射
_MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


def _guess_mime(path: str) -> str:
    """根据文件扩展名猜测 MIME 类型, 未知扩展名按二进制流处理"""
    ext = os.path.splitext(path)[1].lower()
    return _MIME_BY_EXT.get(ext, "application/octet-stream")


def _error_dict(error: str, detail: str) -> Dict:
    """构造统一的失败返回结构"""
    return {"error": error, "detail": detail}


def _http_client(timeout: float) -> httpx.Client:
    """创建 http 客户端: trust_env=False 绕过系统代理

    CrossLister 是本地微服务, 走代理会导致请求被网关改写
    (如目标端口不存在时返回 502 而非连接拒绝), 故显式禁用代理。
    """
    return httpx.Client(timeout=timeout, trust_env=False)


class CrossListerClient:
    """CrossLister 服务 HTTP 客户端 (同步, 基于 httpx)"""

    def __init__(self, base_url: Optional[str] = None):
        """初始化客户端

        Args:
            base_url: 服务地址, 缺省时从环境变量 CROSSLISTER_URL 读取,
                      再缺省回退到 http://localhost:8080
        """
        self.base_url = (
            base_url
            or os.environ.get("CROSSLISTER_URL", "http://localhost:8080")
        ).rstrip("/")

    def health(self) -> dict:
        """健康检查

        返回:
            服务正常: {"status": "ok", ...服务返回的模块状态}
            服务异常: {"status": "error", "message": str}
        """
        try:
            with _http_client(_HEALTH_TIMEOUT) as client:
                resp = client.get("%s/api/v1/health" % self.base_url)
                resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict):
                data = {"modules": data}
            # 服务返回体未带 status 字段时, 能正常响应 200 即视为 ok
            data.setdefault("status", "ok")
            return data
        except Exception as e:
            logger.warning("[crosslister] health check failed: %s", e)
            return {"status": "error", "message": str(e)}

    def generate_listing(
        self,
        image_paths: List[str],
        category: str,
        platform: str = "shopee",
        target_lang: str = "th",
        extra_info: str = "",
    ) -> dict:
        """调用 CrossLister 生成合规多语言 Listing

        Args:
            image_paths: 商品图片本地路径列表 (1-20 张)
            category: 商品类目 (如 "身体护理套装")
            platform: 目标平台, 默认 "shopee" (TikTok Shop 泰国站场景)
            target_lang: 目标语言, 默认 "th" (泰语)
            extra_info: 额外卖家上下文 (可选, 如 SKU/商品名)

        返回:
            成功: {"title": str, "title_zh": str, "bullet_points": List[str],
                   "bullet_points_zh": List[str], "description": str,
                   "description_zh": str, "backend_keywords": ...,
                   "compliance": dict, "visual_analysis": dict, "error": None}
            失败: {"error": str, "detail": str}
        """
        # ── 参数校验: 在发起请求前拦截明显错误 ──
        if not image_paths:
            return _error_dict("no_images", "未提供任何商品图片, 无法生成 Listing")

        if len(image_paths) > 20:
            return _error_dict(
                "too_many_images", "商品图片数量超过上限 20 张 (当前 %d 张)" % len(image_paths)
            )

        missing = [p for p in image_paths if not os.path.isfile(p)]
        if missing:
            return _error_dict(
                "image_not_found", "商品图片文件不存在: %s" % ", ".join(missing[:3])
            )

        # ── 组装 multipart/form-data 请求 ──
        opened_files = []
        try:
            files = []
            for path in image_paths:
                f = open(path, "rb")
                opened_files.append(f)
                files.append(
                    ("images", (os.path.basename(path), f, _guess_mime(path)))
                )

            form_data = {
                "category": category or "通用商品",
                "platform": platform,
                "target_lang": target_lang,
            }
            if extra_info:
                form_data["extra_info"] = extra_info

            try:
                with _http_client(_REQUEST_TIMEOUT) as client:
                    resp = client.post(
                        "%s/api/v1/listing/generate" % self.base_url,
                        files=files,
                        data=form_data,
                    )
            except httpx.TimeoutException as e:
                logger.error("[crosslister] generate timeout after %.0fs", _REQUEST_TIMEOUT)
                return _error_dict("timeout", "Listing 生成超时(%.0fs): %s" % (_REQUEST_TIMEOUT, e))
            except httpx.ConnectError as e:
                logger.error("[crosslister] connect failed: %s", e)
                return _error_dict(
                    "connection_error",
                    "无法连接 Listing 服务 %s, 请确认服务已启动" % self.base_url,
                )
            except httpx.HTTPError as e:
                logger.error("[crosslister] http error: %s", e)
                return _error_dict("http_error", str(e))

            # ── 解析响应 ──
            if resp.status_code != 200:
                detail = resp.text[:300] if resp.text else "无响应内容"
                logger.error(
                    "[crosslister] generate failed: HTTP %d, %s",
                    resp.status_code, detail,
                )
                return _error_dict(
                    "http_%d" % resp.status_code,
                    "Listing 服务返回异常状态码 %d: %s" % (resp.status_code, detail),
                )

            try:
                result = resp.json()
            except ValueError as e:
                logger.error("[crosslister] invalid JSON response: %s", e)
                return _error_dict("invalid_response", "Listing 服务返回了无法解析的响应")

            if not isinstance(result, dict):
                return _error_dict("invalid_response", "Listing 服务返回了非预期的响应格式")

            result["error"] = None
            return result

        except Exception as e:
            logger.error("[crosslister] unexpected error: %s", e, exc_info=True)
            return _error_dict("unexpected_error", str(e))
        finally:
            for f in opened_files:
                try:
                    f.close()
                except Exception:
                    pass


# 全局单例 (与 db_tool 风格一致)
crosslister_client = CrossListerClient()
