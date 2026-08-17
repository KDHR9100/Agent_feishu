from dotenv import load_dotenv
import os
import logging
import threading
from logging.config import dictConfig

load_dotenv()

dictConfig(
    {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "[%(asctime)s] %(levelname)s %(name)s %(module)s:%(lineno)d - %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "level": os.getenv("LOG_LEVEL", "INFO"),
            },
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "filename": "app.log",
                "formatter": "default",
                "level": os.getenv("LOG_LEVEL", "INFO"),
                "encoding": "utf-8",
                "maxBytes": 10 * 1024 * 1024,
                "backupCount": 5,
            },
        },
        "root": {
            "level": os.getenv("LOG_LEVEL", "INFO"),
            "handlers": ["console", "file"],
        },
        "loggers": {
            "uvicorn": {
                "level": os.getenv("LOG_LEVEL", "INFO"),
                "handlers": ["console"],
                "propagate": False,
            },
            "app": {
                "level": os.getenv("LOG_LEVEL", "INFO"),
                "handlers": ["console", "file"],
                "propagate": False,
            },
        },
    }
)

logger = logging.getLogger("app")


class Config:
    LLM_API_KEY = os.getenv("LLM_API_KEY", "") or os.getenv("OPENAI_API_KEY", "")
    LLM_API_BASE = os.getenv("LLM_API_BASE", "") or os.getenv(
        "OPENAI_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "") or os.getenv(
        "OPENAI_MODEL_NAME", "deepseek-v4-pro"
    )
    LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.3"))
    LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "4096"))
    # 主 LLM 请求超时与重试: 缓解 token-plan 端点波动导致的 30s 超时
    # 快速失败原则: 超时短 + 少重试, 避免挂起请求叠加重试拖到分钟级
    LLM_REQUEST_TIMEOUT = float(os.getenv("LLM_REQUEST_TIMEOUT", "45"))
    LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "1"))
    # thinking 开关: qwen3 系列默认开启思考模式会显著增加首 token 与总生成耗时;
    # 本项目所有输出均经 strip_thinking() 剥离思考内容, 思考 token 属纯开销, 默认关闭
    LLM_ENABLE_THINKING = os.getenv("LLM_ENABLE_THINKING", "false").lower() == "true"

    # ===== VLM (视觉语言模型) 配置 =====
    VLM_API_KEY = os.getenv("VLM_API_KEY", "") or os.getenv("LLM_API_KEY", "")
    VLM_API_BASE = os.getenv("VLM_API_BASE", "") or os.getenv(
        "LLM_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    VLM_MODEL_NAME = os.getenv("VLM_MODEL_NAME", "qwen-vl-max")

    EMBEDDING_API_KEY = (
        os.getenv("EMBEDDING_API_KEY", "")
        or os.getenv("LLM_API_KEY", "")
        or os.getenv("OPENAI_API_KEY", "")
    )
    EMBEDDING_API_BASE = (
        os.getenv("EMBEDDING_API_BASE", "")
        or os.getenv("LLM_API_BASE", "")
        or os.getenv(
            "OPENAI_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
    )
    EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "text-embedding-v4")

    USE_LOCAL_EMBEDDING = os.getenv("USE_LOCAL_EMBEDDING", "true").lower() == "true"
    LOCAL_EMBEDDING_MODEL = os.getenv(
        "LOCAL_EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2"
    )

    FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "")
    FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
    FEISHU_BOT_NAME = os.getenv("FEISHU_BOT_NAME", "Ecommerce Agent")
    FEISHU_WEBHOOK_SECRET = os.getenv("FEISHU_WEBHOOK_SECRET", "")
    FEISHU_ENCRYPT_KEY = os.getenv("FEISHU_ENCRYPT_KEY", "")

    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./feishu_agent.db")

    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    APP_PORT = int(os.getenv("APP_PORT", "8000"))

    # token/业务任务日志保留天数: 超期记录由定时任务清理, 防止日志表无限增长
    LOG_RETENTION_DAYS = int(os.getenv("LOG_RETENTION_DAYS", "90"))

    @property
    def OPENAI_API_KEY(self):
        return self.LLM_API_KEY

    @property
    def OPENAI_API_BASE(self):
        return self.LLM_API_BASE

    @property
    def OPENAI_MODEL_NAME(self):
        return self.LLM_MODEL_NAME

    # ===== Router LLM (task routing dedicated fast model) config =====
    ROUTER_API_KEY = os.getenv("ROUTER_API_KEY", "") or os.getenv("LLM_API_KEY", "")
    ROUTER_API_BASE = os.getenv("ROUTER_API_BASE", "") or os.getenv(
        "LLM_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    ROUTER_MODEL_NAME = os.getenv("ROUTER_MODEL_NAME", "") or os.getenv(
        "LLM_MODEL_NAME", "deepseek-v4-pro"
    )
    # router 是分类任务, 温度设 0 保证路由稳定可复现
    ROUTER_TEMPERATURE = float(os.getenv("ROUTER_TEMPERATURE", "0"))
    # router 只做工具选择, 必须快速失败转关键词兜底, 不允许慢重试拖住用户
    ROUTER_REQUEST_TIMEOUT = float(os.getenv("ROUTER_REQUEST_TIMEOUT", "15"))
    ROUTER_MAX_RETRIES = int(os.getenv("ROUTER_MAX_RETRIES", "0"))
    ROUTER_ENABLE_THINKING = (
        os.getenv("ROUTER_ENABLE_THINKING", "false").lower() == "true"
    )

    # ===== 备用模型 (s11) =====
    LLM_FALLBACK_MODEL = os.getenv("LLM_FALLBACK_MODEL", "")
    LLM_FALLBACK_API_KEY = os.getenv("LLM_FALLBACK_API_KEY", "") or os.getenv("LLM_API_KEY", "")
    LLM_FALLBACK_API_BASE = os.getenv("LLM_FALLBACK_API_BASE", "") or os.getenv("LLM_API_BASE", "")

    @property
    def LLM_PROVIDER(self):
        explicit = os.getenv("LLM_PROVIDER", "")
        if explicit:
            return explicit
        if "deepseek" in self.LLM_API_BASE.lower():
            return "DeepSeek"
        elif "dashscope" in self.LLM_API_BASE.lower():
            return "DashScope"
        elif "openai" in self.LLM_API_BASE.lower():
            return "OpenAI"
        else:
            return "Unknown"


config = Config()

# ============================================================
# L4 优化器参数 (损益目标函数调参入口, 按商品类目调整)
# ============================================================
OPTIMIZER_CONFIG = {
    # ---- 价格弹性模型: 销量 = base_sales * (1 + elastic * (竞品价 - 自己的价)/竞品价) ----
    "price_elasticity": float(os.getenv("OPT_PRICE_ELASTICITY", "1.5")),
    "base_sales": float(os.getenv("OPT_BASE_SALES", "200")),          # 基准销量(件/周期)
    "unit_cost": float(os.getenv("OPT_UNIT_COST", "40")),             # 单件成本
    # ---- 成本结构 ----
    "storage_fee_rate": float(os.getenv("OPT_STORAGE_FEE_RATE", "0.5")),   # 仓储费率(元/件/周期)
    "rush_fee_per_unit": float(os.getenv("OPT_RUSH_FEE", "15")),           # 库存不足时的加急费(元/件)
    "ad_effectiveness": float(os.getenv("OPT_AD_EFFECTIVENESS", "0.35")),  # 广告投放对销量的提升系数(边际递减)
    # ---- 蒙特卡洛模拟 ----
    "mc_simulations": int(os.getenv("OPT_MC_SIMS", "1000")),          # 每个候选方案的模拟次数
    "demand_noise_std": float(os.getenv("OPT_DEMAND_NOISE", "0.10")),      # 需求扰动标准差
    "competitor_price_noise_std": float(os.getenv("OPT_COMP_NOISE", "0.03")),  # 竞品价扰动标准差
    # ---- 默认经营上下文 (技能未提供具体数据时的兜底) ----
    "default_price": float(os.getenv("OPT_DEFAULT_PRICE", "99")),
    "default_competitor_price": float(os.getenv("OPT_DEFAULT_COMP_PRICE", "105")),
    "default_inventory": float(os.getenv("OPT_DEFAULT_INVENTORY", "300")),
    "default_ad_budget": float(os.getenv("OPT_DEFAULT_AD_BUDGET", "800")),
}

# ============================================================
# L4 市场哨兵参数 (主动感知层)
# ============================================================
SENTINEL_CONFIG = {
    "poll_interval_minutes": int(os.getenv("SENTINEL_POLL_MINUTES", "30")),
    "price_change_threshold": float(os.getenv("SENTINEL_PRICE_THRESHOLD", "0.03")),    # 竞品价格波动阈值 3%
    "negative_review_threshold": float(os.getenv("SENTINEL_NEG_THRESHOLD", "0.05")),   # 差评率突增阈值 5%(绝对值)
    "top_n": int(os.getenv("SENTINEL_TOP_N", "10")),
    "enabled": os.getenv("SENTINEL_ENABLED", "true").lower() == "true",
}

# ============================================================
# L4 执行层安全开关: 默认 Mock, 显式设置 EXECUTOR_REAL_MODE=true 才允许真实店铺操作
# ============================================================
EXECUTOR_REAL_MODE = os.getenv("EXECUTOR_REAL_MODE", "false").lower() == "true"

_llm_instance = None
_router_llm_instance = None
_fallback_llm_instance = None
_llm_lock = threading.Lock()


def get_router_llm():
    """Task routing dedicated LLM: fast small model, independent key/base configurable via env"""
    global _router_llm_instance
    if _router_llm_instance is None:
        with _llm_lock:
            if _router_llm_instance is not None:
                return _router_llm_instance
            from langchain_openai import ChatOpenAI
            from app.utils.token_tracker import TokenTrackingHandler

            logger.info(
                "Initializing Router LLM: %s (base: %s)"
                % (config.ROUTER_MODEL_NAME, config.ROUTER_API_BASE)
            )
            _router_llm_instance = ChatOpenAI(
                model=config.ROUTER_MODEL_NAME,
                temperature=config.ROUTER_TEMPERATURE,
                max_tokens=2048,
                api_key=config.ROUTER_API_KEY,
                base_url=config.ROUTER_API_BASE,
                timeout=config.ROUTER_REQUEST_TIMEOUT,
                max_retries=config.ROUTER_MAX_RETRIES,
                extra_body={"enable_thinking": config.ROUTER_ENABLE_THINKING},
                callbacks=[TokenTrackingHandler()],
            )
    return _router_llm_instance


def get_llm():
    global _llm_instance
    if _llm_instance is None:
        with _llm_lock:
            if _llm_instance is not None:
                return _llm_instance
            from langchain_openai import ChatOpenAI
            from app.utils.token_tracker import TokenTrackingHandler

            logger.info(
                "Initializing LLM: %s (Provider: %s)"
                % (config.LLM_MODEL_NAME, config.LLM_PROVIDER)
            )
            logger.info("API Base: %s" % config.LLM_API_BASE)
            try:
                _llm_instance = ChatOpenAI(
                    model=config.LLM_MODEL_NAME,
                    temperature=config.LLM_TEMPERATURE,
                    max_tokens=config.LLM_MAX_TOKENS,
                    api_key=config.LLM_API_KEY,
                    base_url=config.LLM_API_BASE,
                    timeout=config.LLM_REQUEST_TIMEOUT,
                    max_retries=config.LLM_MAX_RETRIES,
                    extra_body={"enable_thinking": config.LLM_ENABLE_THINKING},
                    callbacks=[TokenTrackingHandler()],
                )
                logger.info("LLM initialized successfully")
            except Exception as e:
                logger.error("Failed to initialize LLM: %s" % str(e))
                raise
    return _llm_instance


def get_fallback_llm():
    """备用 LLM: 主模型连续失败时由 invoke_with_recovery 自动切换。
    未配置 LLM_FALLBACK_MODEL 时返回 None。"""
    global _fallback_llm_instance
    if _fallback_llm_instance is None:
        if not config.LLM_FALLBACK_MODEL:
            return None
        with _llm_lock:
            if _fallback_llm_instance is not None:
                return _fallback_llm_instance
            from langchain_openai import ChatOpenAI
            from app.utils.token_tracker import TokenTrackingHandler
            logger.info("Initializing Fallback LLM: %s" % config.LLM_FALLBACK_MODEL)
            try:
                _fallback_llm_instance = ChatOpenAI(
                    model=config.LLM_FALLBACK_MODEL,
                    temperature=config.LLM_TEMPERATURE,
                    max_tokens=config.LLM_MAX_TOKENS,
                    api_key=config.LLM_FALLBACK_API_KEY,
                    base_url=config.LLM_FALLBACK_API_BASE,
                    timeout=config.LLM_REQUEST_TIMEOUT,
                    max_retries=0,
                    extra_body={"enable_thinking": config.LLM_ENABLE_THINKING},
                    callbacks=[TokenTrackingHandler()],
                )
                logger.info("Fallback LLM initialized successfully")
            except Exception as e:
                logger.error("Failed to initialize Fallback LLM: %s" % str(e))
                return None
    return _fallback_llm_instance


def get_embeddings():
    # 本地 Embedding 优先（含 ImportError 降级到远程）
    if config.USE_LOCAL_EMBEDDING:
        logger.info("Initializing local Embeddings: %s" % config.LOCAL_EMBEDDING_MODEL)
        try:
            from langchain_huggingface import HuggingFaceEmbeddings

            embeddings = HuggingFaceEmbeddings(
                model_name=config.LOCAL_EMBEDDING_MODEL,
                model_kwargs={"device": "cpu"},
                encode_kwargs={"normalize_embeddings": True},
            )
            logger.info("Local Embeddings initialized successfully")
            return embeddings
        except ImportError:
            logger.warning(
                "Local embedding import failed (langchain_huggingface missing), "
                "falling back to remote Embedding"
            )

    # 远程 Embedding（DashScope / OpenAI 兼容）
    from langchain_openai import OpenAIEmbeddings

    logger.info(
        "Initializing Embeddings: %s (Provider: %s)"
        % (config.EMBEDDING_MODEL_NAME, config.LLM_PROVIDER)
    )
    try:
        embeddings = OpenAIEmbeddings(
            model=config.EMBEDDING_MODEL_NAME,
            api_key=config.EMBEDDING_API_KEY,
            base_url=config.EMBEDDING_API_BASE,
        )
        logger.info("Embeddings initialized successfully")
        return embeddings
    except Exception as e:
        logger.error("Failed to initialize Embeddings: %s" % str(e))
        raise


def log_config_info():
    logger.info("=" * 60)
    logger.info("Application Configuration")
    logger.info("=" * 60)
    logger.info("LLM Provider: %s" % config.LLM_PROVIDER)
    logger.info("Router LLM: %s" % config.ROUTER_MODEL_NAME)
    logger.info("LLM API Key: %s" % ("***" if config.LLM_API_KEY else "NOT SET"))
    logger.info("LLM API Base: %s" % config.LLM_API_BASE)
    logger.info("LLM Model: %s" % config.LLM_MODEL_NAME)
    logger.info("LLM Temperature: %s" % config.LLM_TEMPERATURE)
    logger.info("LLM Max Tokens: %s" % config.LLM_MAX_TOKENS)
    logger.info("-" * 60)
    logger.info("VLM Model: %s" % config.VLM_MODEL_NAME)
    logger.info("VLM API Base: %s" % config.VLM_API_BASE)
    logger.info("VLM API Key: %s" % ("***" if config.VLM_API_KEY else "NOT SET"))
    logger.info("-" * 60)
    logger.info("Use Local Embedding: %s" % config.USE_LOCAL_EMBEDDING)
    logger.info("Local Embedding Model: %s" % config.LOCAL_EMBEDDING_MODEL)
    logger.info("Embedding Model: %s" % config.EMBEDDING_MODEL_NAME)
    logger.info(
        "Embedding API Key: %s" % ("***" if config.EMBEDDING_API_KEY else "NOT SET")
    )
    logger.info("Embedding API Base: %s" % config.EMBEDDING_API_BASE)
    logger.info("-" * 60)
    logger.info("Feishu App ID: %s" % ("***" if config.FEISHU_APP_ID else "NOT SET"))
    logger.info(
        "Feishu App Secret: %s" % ("***" if config.FEISHU_APP_SECRET else "NOT SET")
    )
    logger.info("Feishu Bot Name: %s" % config.FEISHU_BOT_NAME)
    logger.info(
        "Feishu Webhook Secret: %s"
        % ("***" if config.FEISHU_WEBHOOK_SECRET else "NOT SET")
    )
    logger.info("-" * 60)
    logger.info("Database URL: %s" % config.DATABASE_URL)
    logger.info("Log Level: %s" % config.LOG_LEVEL)
    logger.info("App Port: %s" % config.APP_PORT)
    logger.info("=" * 60)