from fastapi import Depends, FastAPI, Header, Request
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import asyncio
import hmac
import time
import os

from app.config import config, logger, log_config_info
from app.monitoring import monitoring_stats

app = FastAPI(title="Ecommerce Agent", version="1.0.0")


# API 鉴权: 当设置了 API_KEY 环境变量时, 敏感端点要求携带匹配的 X-API-Key 请求头
_API_KEY = os.getenv("API_KEY", "")
if not _API_KEY:
    logger.warning(
        "API_KEY is not configured: protected endpoints now reject all requests (fail-closed). "
        "Set the API_KEY environment variable to enable them."
    )


async def require_api_key(x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    # fail-closed: 未配置 API_KEY 时受保护端点默认拒绝, 避免服务在未鉴权状态下暴露
    if not _API_KEY:
        raise HTTPException(status_code=503, detail="API_KEY not configured on server")
    if not hmac.compare_digest(x_api_key or "", _API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")
    return None


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler - catches all unhandled exceptions"""
    logger.error("Unhandled exception on %s %s: %s", request.method, request.url.path, str(exc))
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "message": "An unexpected error occurred, please try again later"}
    )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    """Handle ValueError - common in data parsing"""
    logger.warning("ValueError on %s %s: %s", request.method, request.url.path, str(exc))
    return JSONResponse(
        status_code=400,
        content={"error": "Bad request", "message": "Invalid input format"}
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


# ---------- L4 旁路增强: 优化器 HTTP 路由 (POST /optimize/pricing 等) ----------
from app.optimizer.api import router as optimizer_router  # noqa: E402

app.include_router(optimizer_router)


class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = "default"


class RAGRequest(BaseModel):
    query: str


@app.get("/")
async def root():
    return {"message": "Ecommerce Agent Service Running", "version": "1.0.0"}


@app.get("/health")
async def health_check():
    return monitoring_stats.get_health_status()


@app.get("/health/details")
async def health_check_details():
    return monitoring_stats.get_health_status()


@app.get("/health/jingang")
async def jingang_consumption():
    return monitoring_stats.get_jingang_consumption()


@app.post("/chat")
async def chat(request: ChatRequest, _: None = Depends(require_api_key)):
    try:
        logger.info(
            "Received chat request: conversation_id=%s" % request.conversation_id
        )
        start_time = time.time()

        # 重构后: 单一 workflow 入口, 原 use_coordinator 分支已删除
        # 多 Agent 协作能力合并进 LangGraph (skill_executor + answer 综合)
        from app.agent.workflow import agent

        logger.debug("Using workflow mode")
        # 避免同步 invoke 阻塞事件循环（并发请求互相卡死）
        result = await asyncio.to_thread(
            agent.invoke,
            {
                "user_input": request.message,
                "conversation_id": request.conversation_id,
            },
        )
        duration = time.time() - start_time
        monitoring_stats.record_skill_call("workflow", duration)
        if "intent" in result:
            monitoring_stats.record_intent(result["intent"])
        if "token_usage" in result:
            monitoring_stats.record_llm_call(
                duration, token_usage=result["token_usage"]
            )
        logger.info("Workflow response time: %.2fs" % duration)
        return {
            "status": "success",
            "answer": result.get("answer", ""),
            "conversation_id": request.conversation_id,
            "intent": result.get("intent"),
            "token_usage": result.get("token_usage"),
        }
    except Exception as e:
        logger.error("Chat error: %s" % str(e), exc_info=True)
        monitoring_stats.record_skill_call("chat", 0, success=False)
        raise HTTPException(status_code=500, detail="内部服务错误，请稍后重试")


@app.post("/rag/query")
async def rag_query(request: RAGRequest, _: None = Depends(require_api_key)):
    try:
        logger.info("Received RAG query: %s..." % request.query[:50])
        start_time = time.time()

        from app.rag.retriever import rag_retriever

        result = rag_retriever.retrieve_and_generate(request.query)

        duration = time.time() - start_time
        monitoring_stats.record_rag_query(duration)
        logger.info("RAG response time: %.2fs" % duration)
        return {
            "status": "success",
            "answer": result.get("answer", ""),
            "sources": result.get("retrieved_docs", []),
        }
    except Exception as e:
        logger.error("RAG query error: %s" % str(e), exc_info=True)
        monitoring_stats.record_rag_query(0, success=False)
        raise HTTPException(status_code=500, detail="RAG 查询失败，请稍后重试")


@app.on_event("startup")
async def startup_event():

    logger.info("=" * 60)
    logger.info("Ecommerce Agent Service Starting...")
    logger.info("=" * 60)

    log_config_info()

    logger.info("Loading dependencies...")

    try:
        logger.info("Initializing database...")
        from app.models import init_db

        init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error("Failed to initialize database: %s" % str(e), exc_info=True)

    try:
        logger.info("Loading agents module...")
        logger.info("Agents module loaded successfully")
    except Exception as e:
        logger.error("Failed to load agents module: %s" % str(e), exc_info=True)

    try:
        logger.info("Loading workflow module...")
        logger.info("Workflow module loaded successfully")
    except Exception as e:
        logger.error("Failed to load workflow module: %s" % str(e), exc_info=True)

    try:
        logger.info("Loading RAG retriever (this may take a moment)...")
        import threading
        import queue

        def load_rag(q):
            try:
                from app.rag.vectorstore import vector_store

                vector_store.initialize()
                q.put(("success", "RAG retriever loaded successfully"))
            except Exception as e:
                q.put(("error", str(e)))

        q = queue.Queue()
        t = threading.Thread(target=load_rag, args=(q,))
        t.daemon = True
        t.start()
        t.join(timeout=180)

        if t.is_alive():
            logger.warning("RAG retriever loading timed out (180s), skipping for now")
        else:
            status, msg = q.get()
            if status == "success":
                logger.info(msg)
            else:
                logger.error("Failed to load RAG retriever: %s" % msg)
    except Exception as e:
        logger.error("RAG loading error: %s" % str(e), exc_info=True)

    # try:
    # Webhook router disabled (switched to WebSocket long connection)
    #         logger.info("Loading Feishu router...")
    #         from app.api.feishu import router as feishu_router
    #         app.include_router(feishu_router)
    #         logger.info("Feishu router loaded successfully")
    #     except Exception as e:
    #         logger.error("Failed to load Feishu router: %s" % str(e), exc_info=True)

    try:
        logger.info("Starting Feishu WebSocket client with health monitor...")
        from app.tools.ws_manager import ws_manager
        ws_manager.start(config.FEISHU_APP_ID, config.FEISHU_APP_SECRET)
    except Exception as e:
        logger.error(
            "Failed to start Feishu WebSocket client: %s" % str(e), exc_info=True
        )

    # 启动定时任务调度器
    try:
        logger.info("Starting TaskScheduler...")
        from app.tasks import task_scheduler
        task_scheduler.start()
        logger.info("TaskScheduler started successfully")
    except Exception as e:
        logger.error("Failed to start TaskScheduler: %s" % str(e), exc_info=True)

    # ---------- L4 旁路子系统初始化 (不改动既有 12 技能注册) ----------
    try:
        from app.config import SENTINEL_CONFIG
        from app.sentinel.trigger_engine import sentinel
        if SENTINEL_CONFIG["enabled"]:
            sentinel.start()
            logger.info(
                "L4 market sentinel started (interval=%d min)",
                SENTINEL_CONFIG["poll_interval_minutes"],
            )
        else:
            logger.info("L4 market sentinel disabled (SENTINEL_ENABLED=false)")
    except Exception as e:
        logger.error("Failed to start L4 sentinel: %s" % str(e), exc_info=True)

    try:
        from app.executor.rollback_manager import get_rollback_manager
        get_rollback_manager().start()
        logger.info("L4 rollback sweeper started (confirm window=1h)")
    except Exception as e:
        logger.error("Failed to start L4 rollback sweeper: %s" % str(e), exc_info=True)

    try:
        from app.config import EXECUTOR_REAL_MODE
        from app.executor.platform_adapter import get_store_api
        _store_api = get_store_api()
        logger.info(
            "L4 store adapter ready: platform=%s real_mode=%s",
            _store_api.platform, EXECUTOR_REAL_MODE,
        )
    except Exception as e:
        logger.error("Failed to init L4 store adapter: %s" % str(e), exc_info=True)

    logger.info("=" * 60)
    logger.info("Ecommerce Agent Service Started Successfully")
    logger.info("Service will be available at: http://localhost:%s" % config.APP_PORT)
    logger.info("=" * 60)


@app.on_event("shutdown")
async def shutdown_event():

    logger.info("=" * 60)
    logger.info("Ecommerce Agent Service Shutting Down...")
    logger.info("=" * 60)

    # 停止定时任务调度器
    try:
        from app.tasks import task_scheduler
        task_scheduler.stop()
        logger.info("TaskScheduler stopped")
    except Exception as e:
        logger.error("Failed to stop TaskScheduler: %s" % str(e), exc_info=True)

    # ---------- L4 旁路子系统停机 ----------
    try:
        from app.sentinel.trigger_engine import sentinel
        sentinel.stop()
        logger.info("L4 market sentinel stopped")
    except Exception as e:
        logger.error("Failed to stop L4 sentinel: %s" % str(e), exc_info=True)

    try:
        from app.executor.rollback_manager import get_rollback_manager
        get_rollback_manager().shutdown()
        logger.info("L4 rollback sweeper stopped")
    except Exception as e:
        logger.error("Failed to stop L4 rollback sweeper: %s" % str(e), exc_info=True)

    try:
        from app.tools.ws_manager import ws_manager
        ws_manager.stop()
        logger.info("Feishu WebSocket client stopped")
    except Exception as e:
        logger.error("Failed to stop Feishu WS client: %s" % str(e), exc_info=True)


if __name__ == "__main__":
    import uvicorn

    logger.info("Starting uvicorn server on port %s" % config.APP_PORT)
    uvicorn.run(
        app, host="127.0.0.1", port=config.APP_PORT, log_level=config.LOG_LEVEL.lower()
    )


@app.get("/ws/status")
async def ws_status():
    """Get WebSocket client status."""
    from app.tools.ws_manager import ws_manager
    return ws_manager.get_status()


@app.get("/tasks/status")
async def tasks_status():
    """Get scheduled tasks status."""
    from app.tasks import task_scheduler
    return task_scheduler.get_status()


# ============================================================
# Document Management & RAG API
# ============================================================

@app.get("/documents")
async def list_documents():
    """List all documents in the document folder."""
    from app.rag.doc_manager import doc_vector_manager
    return doc_vector_manager.get_status()


@app.post("/documents")
async def add_document(name: str, content: str, _: None = Depends(require_api_key)):
    """Add a new document and sync vector store."""
    from app.rag.doc_manager import doc_vector_manager
    doc_vector_manager.doc_manager.add_document(name, content)
    result = doc_vector_manager.sync()
    return {"status": "added", "name": name, "sync": result}


@app.delete("/documents/{name}")
async def delete_document(name: str, _: None = Depends(require_api_key)):
    """Delete a document and sync vector store."""
    from app.rag.doc_manager import doc_vector_manager
    deleted = doc_vector_manager.doc_manager.delete_document(name)
    if not deleted:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Document not found")
    result = doc_vector_manager.sync()
    return {"status": "deleted", "name": name, "sync": result}


@app.post("/rag/sync")
async def sync_vector_store(force: bool = False, _: None = Depends(require_api_key)):
    """Sync documents with vector store."""
    from app.rag.doc_manager import doc_vector_manager
    result = doc_vector_manager.sync(force_rebuild=force)
    return result


@app.get("/rag/status")
async def rag_status():
    """Get RAG system status."""
    from app.rag.doc_manager import doc_vector_manager
    return doc_vector_manager.get_status()


# ============================================================
# Token Usage Metrics API
# ============================================================

@app.get("/metrics/usage")
async def metrics_usage(_: None = Depends(require_api_key)):
    """Get token usage ranking for the last 24 hours."""
    return monitoring_stats.get_usage_last_24h()


@app.post("/approval/{approval_id}/resolve")
async def resolve_approval(approval_id: str, approved: bool, _: None = Depends(require_api_key)):
    """Resolve a pending approval (approve or reject)."""
    import threading
    from app.utils.approval import approval_manager
    from app.utils.action_log import log_action
    ok = approval_manager.resolve(approval_id, approved)
    if not ok:
        raise HTTPException(status_code=404, detail="Approval not found or already resolved")
    log_action(approval_id=approval_id, decision="approved" if approved else "rejected",
               operator="api")
    if approved:
        # 批准后后台执行被挂起的技能（与飞书卡片回调路径一致）
        threading.Thread(
            target=approval_manager.take_and_execute,
            args=(approval_id,),
            daemon=True,
        ).start()
    return {"approval_id": approval_id, "approved": approved, "resolved": True}


# ============================================================
# L4 旁路增强: 仲裁 / 哨兵 / 执行确认 测试端点
# ============================================================

class ConflictResolveRequest(BaseModel):
    user_input: str
    conversation_id: Optional[str] = ""
    context: Optional[dict] = None


@app.post("/optimize/resolve-conflict")
async def resolve_conflict_endpoint(req: ConflictResolveRequest, _: None = Depends(require_api_key)):
    """任务12 仲裁入口: 识别冲突目标并生成帕累托决策看板 (A/B 方案)"""
    from app.optimizer.conflict_resolver import get_conflict_resolver
    return get_conflict_resolver().resolve(
        req.user_input, ctx=req.context, conversation_id=req.conversation_id or "")


class ConflictChoiceRequest(BaseModel):
    resolver_id: str
    choice: str
    conversation_id: Optional[str] = ""


@app.post("/optimize/choose-option")
async def choose_option_endpoint(req: ConflictChoiceRequest, _: None = Depends(require_api_key)):
    """任务12 仲裁点选: 用户选定方案后走 executor 审批闭环"""
    from app.optimizer.conflict_resolver import get_conflict_resolver
    return get_conflict_resolver().apply_choice(
        req.resolver_id, req.choice, req.conversation_id or "")


@app.post("/sentinel/check")
async def sentinel_check_endpoint(_: None = Depends(require_api_key)):
    """任务9 哨兵手动触发一次巡检 (Checkpoint1 联调用)"""
    from app.sentinel.event_bus import event_bus
    from app.sentinel.trigger_engine import sentinel
    alerts = sentinel.check_once()
    return {
        "status": "ok",
        "alerts": alerts,
        "sentinel_status": sentinel.get_status(),
        "recent_events": event_bus.get_history()[-10:],
    }


@app.post("/executor/confirm/{action_id}")
async def confirm_action_endpoint(action_id: str, _: None = Depends(require_api_key)):
    """任务11 人工确认执行完成: 确认后不再自动回滚"""
    from app.executor.rollback_manager import get_rollback_manager
    ok = get_rollback_manager().confirm(action_id)
    return {"action_id": action_id, "confirmed": ok}


@app.get("/executor/status/{action_id}")
async def action_status_endpoint(action_id: str, _: None = Depends(require_api_key)):
    """任务11 查询动作状态 (awaiting_confirmation/confirmed/rolled_back)"""
    from app.executor.rollback_manager import get_rollback_manager
    entry = get_rollback_manager().get(action_id)
    if not entry:
        raise HTTPException(status_code=404, detail="action not found")
    return {"action_id": action_id, "entry": entry}
