from app.config import get_llm, logger
from app.rag.vectorstore import vector_store


class RAGRetriever:
    def __init__(self):
        self.llm = get_llm()
        self.vector_store = vector_store

    def retrieve_and_generate(self, query):
        try:
            logger.info("RAG query: %s" % query[:50])

            if self.vector_store and self.vector_store.vector_store:
                docs = self.vector_store.similarity_search(query, k=3)
                context = "\n\n".join([doc.page_content for doc in docs])

                prompt = """Use the following pieces of context to answer the question. 
If you don't know the answer, just say that you don't know.

Context: %s

Question: %s

Answer:""" % (context, query)

                result = self.llm.invoke(prompt)
                return {
                    "answer": str(result),
                    "retrieved_docs": [doc.page_content for doc in docs],
                }
            else:
                logger.warning(
                    "Vector store not available, returning direct LLM response"
                )
                result = self.llm.invoke(query)
                return {"answer": str(result), "retrieved_docs": []}
        except Exception as e:
            logger.error("RAG query error: %s" % str(e))
            return {"answer": "Error: %s" % str(e), "retrieved_docs": []}


rag_retriever = RAGRetriever()
