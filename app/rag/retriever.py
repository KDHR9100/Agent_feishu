from app.config import get_llm, logger
from app.rag.doc_manager import doc_vector_manager


class RAGRetriever:
    def __init__(self):
        self.llm = get_llm()
        self.manager = doc_vector_manager

    def retrieve_and_generate(self, query):
        try:
            logger.info("RAG query: %s" % query[:50])

            # Smart query: cache -> vector store -> cache
            results, from_cache = self.manager.query(query, k=3)

            if not results:
                logger.warning("No results from vector store, direct LLM response")
                result = self.llm.invoke(query)
                return {"answer": str(result), "retrieved_docs": [], "from_cache": False}

            context = "\n\n".join(results)

            prompt = """Based on the following context, answer the question.
If the context does not contain relevant info, say you don't know.

Context: %s

Question: %s

Answer:""" % (context, query)

            result = self.llm.invoke(prompt)

            # Extract text after </think> if present
            answer = str(result)
            if "</think>" in answer:
                answer = answer.rsplit("</think>", 1)[-1].strip()

            return {
                "answer": answer,
                "retrieved_docs": [t[:200] for t in results],
                "from_cache": from_cache,
            }
        except Exception as e:
            logger.error("RAG query error: %s" % str(e))
            return {"answer": "RAG query failed, please try again later", "retrieved_docs": [], "from_cache": False}


rag_retriever = RAGRetriever()
