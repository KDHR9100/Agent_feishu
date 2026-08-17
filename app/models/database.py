import logging

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker

from app.config import config

logger = logging.getLogger("app.models.database")

# timeout=30: SQLite busy timeout(秒), 并发写冲突时等待而非立即抛 "database is locked"
engine = create_engine(
    config.DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):
    """WAL 模式: 读写互不阻塞, 支撑 workflow/APScheduler/WS 回调多线程并发写"""
    try:
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
    except Exception as e:
        # 非 SQLite 后端或内存库时降级为默认模式, 不影响启动
        logger.warning("SQLite WAL mode not enabled: %s", e)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
