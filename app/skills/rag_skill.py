from app.config import logger


def rag_skill(user_input: str) -> dict:
    try:
        from app.rag.retriever import rag_retriever
        result = rag_retriever.retrieve_and_generate(user_input)
        answer = result.get("answer", "")
        return {
            "type": "rag_answer",
            "data": {
                "analysis": answer,
                "retrieved_docs": result.get("retrieved_docs", []),
                "from_cache": result.get("from_cache", False),
            },
        }
    except Exception as e:
        logger.error("rag_skill error: %s", e)
        return {
            "type": "rag_answer",
            "data": {
                "analysis": "RAG query temporarily unavailable.",
                "error": str(e),
            },
        }
