from app.config import logger


# "列文档" 意图关键词: 运营人员查看文件库内容的常见说法
_DOC_LIST_KEYWORDS = [
    "文件库", "文档列表", "文件列表", "列出文档", "列出文件",
    "哪些文档", "哪些文件", "有什么文档", "有什么文件",
    "知识库里有什么", "看看文档", "看看文件",
]


def _is_doc_list_request(user_input: str) -> bool:
    """判断是否为查看文件库文档列表的请求"""
    text = (user_input or "").strip()
    return any(kw in text for kw in _DOC_LIST_KEYWORDS)


def _list_documents_answer() -> str:
    """生成文件库文档清单的回复文本"""
    from datetime import datetime
    from app.rag.doc_manager import doc_vector_manager

    docs = doc_vector_manager.doc_manager.list_documents()
    if not docs:
        return (
            "📁 文件库目前是空的，还没有上传任何文档。\n\n"
            "支持通过管理端点上传 txt / markdown / csv / json 等文档，"
            "上传后我就能基于它们回答问题啦。"
        )
    lines = ["📁 文件库共有 **%d** 份文档：" % len(docs), ""]
    for d in docs:
        size_kb = d["size"] / 1024.0
        modified = datetime.fromtimestamp(d["modified"]).strftime("%Y-%m-%d %H:%M")
        lines.append("• **%s**（%.1f KB，更新于 %s）" % (d["name"], size_kb, modified))
    lines.append("")
    lines.append("可以直接问我这些文档里的内容，例如「佣金规则是什么」。")
    return "\n".join(lines)


def rag_skill(user_input: str) -> dict:
    # 查看文件库清单: 直接列文档, 不走检索
    if _is_doc_list_request(user_input):
        try:
            answer = _list_documents_answer()
        except Exception as e:
            logger.error("rag_skill list documents error: %s", e)
            answer = "文件库查询暂时不可用：%s" % e
        return {
            "type": "rag_answer",
            "data": {"analysis": answer, "retrieved_docs": [], "from_cache": False},
        }
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
