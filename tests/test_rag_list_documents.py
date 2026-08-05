"""rag_skill 文件库列文档意图测试"""
from app.skills.rag_skill import _is_doc_list_request, rag_skill


def test_doc_list_intent_hit():
    for text in ["文件库内有哪些文档，让我看看", "文档列表", "知识库里有什么",
                 "帮我列出文档", "看看文档"]:
        assert _is_doc_list_request(text), "未命中: %r" % text


def test_doc_list_intent_miss():
    for text in ["佣金规则是什么", "上架流程", "帮我写一段文案"]:
        assert not _is_doc_list_request(text), "误命中: %r" % text


def test_rag_skill_returns_doc_list():
    """列文档请求返回 rag_answer 且包含清单文案, 不抛异常"""
    result = rag_skill("文件库内有哪些文档")
    assert result["type"] == "rag_answer"
    assert "文件库" in result["data"]["analysis"]
