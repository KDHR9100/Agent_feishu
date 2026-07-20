from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import logging
import time

from app.config import config, logger, log_config_info

app = FastAPI(title="Ecommerce Agent", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = "default"
    use_coordinator: Optional[bool] = False

class RAGRequest(BaseModel):
    query: str

@app.get("/")
async def root():
    return {"message": "Ecommerce Agent Service Running", "version": "1.0.0"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.post("/chat")
async def chat(request: ChatRequest):
    try:
        logger.info("Received chat request: conversation_id=%s, use_coordinator=%s" % (request.conversation_id, request.use_coordinator))
        start_time = time.time()
        
        if request.use_coordinator:
            from app.agents.coordinator import coordinator
            logger.debug("Using coordinator mode")
            result = coordinator.route_and_coordinate(request.message)
            logger.info("Coordinator response time: %.2fs" % (time.time() - start_time))
            return {
                "status": "success",
                "answer": result.get("summary", str(result)),
                "details": result
            }
        else:
            from app.agent.workflow import agent
            logger.debug("Using workflow mode")
            result = agent.invoke({
                "user_input": request.message,
                "conversation_id": request.conversation_id
            })
            logger.info("Workflow response time: %.2fs" % (time.time() - start_time))
            return {
                "status": "success",
                "answer": result.get("answer", ""),
                "conversation_id": request.conversation_id
            }
    except Exception as e:
        logger.error("Chat error: %s" % str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/rag/query")
async def rag_query(request: RAGRequest):
    try:
        logger.info("Received RAG query: %s..." % request.query[:50])
        start_time = time.time()
        
        from app.rag.retriever import rag_retriever
        result = rag_retriever.retrieve_and_generate(request.query)
        
        logger.info("RAG response time: %.2fs" % (time.time() - start_time))
        return {
            "status": "success",
            "answer": result.get("answer", ""),
            "sources": result.get("retrieved_docs", [])
        }
    except Exception as e:
        logger.error("RAG query error: %s" % str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.on_event("startup")
async def startup_event():
    logger.info("=" * 60)
    logger.info("Ecommerce Agent Service Starting...")
    logger.info("=" * 60)
    
    log_config_info()
    
    logger.info("Loading dependencies...")
    
    try:
        logger.info("Loading agents module...")
        from app.agents.coordinator import coordinator
        logger.info("Agents module loaded successfully")
    except Exception as e:
        logger.error("Failed to load agents module: %s" % str(e), exc_info=True)
    
    try:
        logger.info("Loading workflow module...")
        from app.agent.workflow import agent
        logger.info("Workflow module loaded successfully")
    except Exception as e:
        logger.error("Failed to load workflow module: %s" % str(e), exc_info=True)
    
    try:
        logger.info("Loading RAG retriever (this may take a moment)...")
        import threading
        import queue
        
        def load_rag(q):
            try:
                from app.rag.retriever import rag_retriever
                q.put(("success", "RAG retriever loaded successfully"))
            except Exception as e:
                q.put(("error", str(e)))
        
        q = queue.Queue()
        t = threading.Thread(target=load_rag, args=(q,))
        t.daemon = True
        t.start()
        t.join(timeout=30)
        
        if t.is_alive():
            logger.warning("RAG retriever loading timed out (30s), skipping for now")
        else:
            status, msg = q.get()
            if status == "success":
                logger.info(msg)
            else:
                logger.error("Failed to load RAG retriever: %s" % msg)
    except Exception as e:
        logger.error("RAG loading error: %s" % str(e), exc_info=True)
    
    try:
        logger.info("Loading Feishu router...")
        from app.api.feishu import router as feishu_router
        app.include_router(feishu_router)
        logger.info("Feishu router loaded successfully")
    except Exception as e:
        logger.error("Failed to load Feishu router: %s" % str(e), exc_info=True)
    
    logger.info("=" * 60)
    logger.info("Ecommerce Agent Service Started Successfully")
    logger.info("Service will be available at: http://localhost:%s" % config.APP_PORT)
    logger.info("=" * 60)

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("=" * 60)
    logger.info("Ecommerce Agent Service Shutting Down...")
    logger.info("=" * 60)

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting uvicorn server on port %s" % config.APP_PORT)
    uvicorn.run(app, host="0.0.0.0", port=config.APP_PORT, log_level=config.LOG_LEVEL.lower())
