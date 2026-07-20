from dotenv import load_dotenv
import os
import logging
from logging.config import dictConfig

load_dotenv()

dictConfig({
    'version': 1,
    'formatters': {
        'default': {
            'format': '[%(asctime)s] %(levelname)s %(name)s %(module)s:%(lineno)d - %(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S'
        }
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'default',
            'level': os.getenv('LOG_LEVEL', 'INFO')
        },
        'file': {
            'class': 'logging.FileHandler',
            'filename': 'app.log',
            'formatter': 'default',
            'level': os.getenv('LOG_LEVEL', 'INFO'),
            'encoding': 'utf-8'
        }
    },
    'root': {
        'level': os.getenv('LOG_LEVEL', 'INFO'),
        'handlers': ['console', 'file']
    },
    'loggers': {
        'uvicorn': {
            'level': os.getenv('LOG_LEVEL', 'INFO'),
            'handlers': ['console'],
            'propagate': False
        },
        'app': {
            'level': os.getenv('LOG_LEVEL', 'INFO'),
            'handlers': ['console', 'file'],
            'propagate': False
        }
    }
})

logger = logging.getLogger('app')

class Config:
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
    OPENAI_MODEL_NAME = os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini")
    LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.3"))
    LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "2000"))

    FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "")
    FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
    FEISHU_BOT_NAME = os.getenv("FEISHU_BOT_NAME", "Ecommerce Agent")
    FEISHU_WEBHOOK_SECRET = os.getenv("FEISHU_WEBHOOK_SECRET", "")

    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./feishu_agent.db")

    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    APP_PORT = int(os.getenv("APP_PORT", "8000"))

config = Config()

_llm_instance = None

def get_llm():
    global _llm_instance
    if _llm_instance is None:
        from langchain_openai import ChatOpenAI
        logger.info("Initializing LLM: %s" % config.OPENAI_MODEL_NAME)
        try:
            _llm_instance = ChatOpenAI(
                model=config.OPENAI_MODEL_NAME,
                temperature=config.LLM_TEMPERATURE,
                max_tokens=config.LLM_MAX_TOKENS,
                api_key=config.OPENAI_API_KEY,
                base_url=config.OPENAI_API_BASE,
            )
            logger.info("LLM initialized successfully")
        except Exception as e:
            logger.error("Failed to initialize LLM: %s" % str(e))
            raise
    return _llm_instance

def log_config_info():
    logger.info("=" * 60)
    logger.info("Application Configuration")
    logger.info("=" * 60)
    logger.info("OpenAI API Key: %s" % ('***' if config.OPENAI_API_KEY else 'NOT SET'))
    logger.info("OpenAI API Base: %s" % config.OPENAI_API_BASE)
    logger.info("OpenAI Model: %s" % config.OPENAI_MODEL_NAME)
    logger.info("LLM Temperature: %s" % config.LLM_TEMPERATURE)
    logger.info("LLM Max Tokens: %s" % config.LLM_MAX_TOKENS)
    logger.info("-" * 60)
    logger.info("Feishu App ID: %s" % ('***' if config.FEISHU_APP_ID else 'NOT SET'))
    logger.info("Feishu App Secret: %s" % ('***' if config.FEISHU_APP_SECRET else 'NOT SET'))
    logger.info("Feishu Bot Name: %s" % config.FEISHU_BOT_NAME)
    logger.info("Feishu Webhook Secret: %s" % ('***' if config.FEISHU_WEBHOOK_SECRET else 'NOT SET'))
    logger.info("-" * 60)
    logger.info("Database URL: %s" % config.DATABASE_URL)
    logger.info("Log Level: %s" % config.LOG_LEVEL)
    logger.info("App Port: %s" % config.APP_PORT)
    logger.info("=" * 60)
