from dotenv import load_dotenv
import os
import logging
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
    LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "2000"))
    # 主 LLM 请求超时与重试: 缓解 token-plan 端点波动导致的 30s 超时
    LLM_REQUEST_TIMEOUT = float(os.getenv("LLM_REQUEST_TIMEOUT", "60"))
    LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "2"))

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

_llm_instance = None
_router_llm_instance = None


def get_router_llm():
    """Task routing dedicated LLM: fast small model, independent key/base configurable via env"""
    global _router_llm_instance
    if _router_llm_instance is None:
        from langchain_openai import ChatOpenAI
        from app.utils.token_tracker import TokenTrackingHandler

        logger.info(
            "Initializing Router LLM: %s (base: %s)"
            % (config.ROUTER_MODEL_NAME, config.ROUTER_API_BASE)
        )
        _router_llm_instance = ChatOpenAI(
            model=config.ROUTER_MODEL_NAME,
            temperature=config.ROUTER_TEMPERATURE,
            max_tokens=config.LLM_MAX_TOKENS,
            api_key=config.ROUTER_API_KEY,
            base_url=config.ROUTER_API_BASE,
            callbacks=[TokenTrackingHandler()],
        )
    return _router_llm_instance


def get_llm():
    global _llm_instance
    if _llm_instance is None:
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
                callbacks=[TokenTrackingHandler()],
            )
            logger.info("LLM initialized successfully")
        except Exception as e:
            logger.error("Failed to initialize LLM: %s" % str(e))
            raise
    return _llm_instance


def get_embeddings():
    if config.USE_LOCAL_EMBEDDING:
        logger.info("Initializing local Embeddings: %s" % config.LOCAL_EMBEDDING_MODEL)
        try:
            from langchain_huggingface import HuggingFaceEmbeddings

            embeddings = HuggingFaceEmbeddings(
                model_name=config.LOCAL_EMBEDDING_MODEL,
                model_kwargs={"device": "cpu"},
                encode_kwargs={"normalize_embeddings": True},
            )
        except ImportError:
            from langchain_huggingface import HuggingFaceEmbeddings

            embeddings = HuggingFaceEmbeddings(
                model_name=config.LOCAL_EMBEDDING_MODEL,
                model_kwargs={"device": "cpu"},
                encode_kwargs={"normalize_embeddings": True},
            )
        logger.info("Local Embeddings initialized successfully")
        return embeddings
    else:
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