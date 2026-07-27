from fastapi import FastAPI, Request
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import time
import subprocess
import sys

from app.config import config, logger, log_config_info
from app.monitoring import monitoring_stats

app = FastAPI(title="Ecommerce Agent", version="1.0.0")

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
async def chat(request: ChatRequest):
    try:
        logger.info(
            "Received chat request: conversation_id=%s" % request.conversation_id
        )
        start_time = time.time()

        # 重构后: 单一 workflow 入口, 原 use_coordinator 分支已删除
        # 多 Agent 协作能力合并进 LangGraph (skill_executor + answer 综合)
        from app.agent.workflow import agent

        logger.debug("Using workflow mode")
        result = agent.invoke(
            {
                "user_input": request.message,
                "conversation_id": request.conversation_id,
            }
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
async def rag_query(request: RAGRequest):
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


feishu_ws_process = None


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
        logger.info("Starting Feishu WebSocket client...")
        if config.FEISHU_APP_ID and config.FEISHU_APP_SECRET:
            feishu_ws_process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "app.tools.feishu_ws",
                    config.FEISHU_APP_ID,
                    config.FEISHU_APP_SECRET,
                ],
                stdout=None,
                stderr=None,
                text=True,
            )
            logger.info(
                "Feishu WebSocket client started in separate process (PID: %d)"
                % feishu_ws_process.pid
            )
        else:
            logger.warning("Feishu credentials not configured, skipping WS client")
    except Exception as e:
        logger.error(
            "Failed to start Feishu WebSocket client: %s" % str(e), exc_info=True
        )

    logger.info("=" * 60)
    logger.info("Ecommerce Agent Service Started Successfully")
    logger.info("Service will be available at: http://localhost:%s" % config.APP_PORT)
    logger.info("=" * 60)


@app.on_event("shutdown")
async def shutdown_event():

    logger.info("=" * 60)
    logger.info("Ecommerce Agent Service Shutting Down...")
    logger.info("=" * 60)

    if feishu_ws_process:
        try:
            logger.info(
                "Stopping Feishu WebSocket client (PID: %d)..." % feishu_ws_process.pid
            )
            feishu_ws_process.terminate()
            feishu_ws_process.wait(timeout=5)
            logger.info("Feishu WebSocket client stopped")
        except Exception as e:
            logger.error("Failed to stop Feishu WS client: %s" % str(e), exc_info=True)


if __name__ == "__main__":
    import uvicorn

    logger.info("Starting uvicorn server on port %s" % config.APP_PORT)
    uvicorn.run(
        app, host="127.0.0.1", port=config.APP_PORT, log_level=config.LOG_LEVEL.lower()
    )


# ============================================================
# Document Management & RAG API
# ============================================================

@app.get("/documents")
async def list_documents():
    """List all documents in the document folder."""
    from app.rag.doc_manager import doc_vector_manager
    return doc_vector_manager.get_status()


@app.post("/documents")
async def add_document(name: str, content: str):
    """Add a new document and sync vector store."""
    from app.rag.doc_manager import doc_vector_manager
    doc_vector_manager.doc_manager.add_document(name, content)
    result = doc_vector_manager.sync()
    return {"status": "added", "name": name, "sync": result}


@app.delete("/documents/{name}")
async def delete_document(name: str):
    """Delete a document and sync vector store."""
    from app.rag.doc_manager import doc_vector_manager
    deleted = doc_vector_manager.doc_manager.delete_document(name)
    if not deleted:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Document not found")
    result = doc_vector_manager.sync()
    return {"status": "deleted", "name": name, "sync": result}


@app.post("/rag/sync")
async def sync_vector_store(force: bool = False):
    """Sync documents with vector store."""
    from app.rag.doc_manager import doc_vector_manager
    result = doc_vector_manager.sync(force_rebuild=force)
    return result


@app.get("/rag/status")
async def rag_status():
    """Get RAG system status."""
    from app.rag.doc_manager import doc_vector_manager
    return doc_vector_manager.get_status()
