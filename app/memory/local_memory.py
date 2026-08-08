import logging
from collections import OrderedDict
from typing import List, Dict, Optional
from datetime import datetime

logger = logging.getLogger("local_memory")

# 摘要触发阈值: 消息超过此数量时, 对旧消息做 LLM 摘要
SUMMARIZE_THRESHOLD = 50
# 摘要后保留的最近原文消息数
RECENT_KEEP_COUNT = 30
# P10: 历史超出最近窗口且无摘要时, 把最早的 N 条消息提炼为锚定摘要 (用户最初的问题陈述)
ANCHOR_KEEP_COUNT = 4


class LocalMemory:
    def __init__(self, max_history: int = 60, max_conversations: int = 1000):
        self.conversations: OrderedDict[str, List[Dict]] = OrderedDict()
        self.max_history = max_history
        self.max_conversations = max_conversations
        # 每个 conversation_id 对应的历史摘要
        self._summaries: Dict[str, str] = {}
        self._db_available = self._check_db()

    def _check_db(self) -> bool:
        try:
            from app.models.database import engine, Base
            Base.metadata.create_all(bind=engine)
            logger.info("[memory] SQLite persistence enabled")
            return True
        except Exception as e:
            logger.warning("[memory] SQLite unavailable (%s)", e)
            return False

    def _get_session(self):
        from app.models.database import SessionLocal
        return SessionLocal()

    def _load_from_db(self, conversation_id: str) -> List[Dict]:
        if not self._db_available:
            return []
        try:
            from app.models.models import Conversation
            session = self._get_session()
            try:
                rows = (
                    session.query(Conversation)
                    .filter(Conversation.conversation_id == conversation_id)
                    .order_by(Conversation.created_at.asc())
                    .limit(self.max_history)
                    .all()
                )
                return [
                    {"role": r.role, "content": r.content,
                     "timestamp": r.created_at.isoformat() if r.created_at else ""}
                    for r in rows
                ]
            finally:
                session.close()
        except Exception as e:
            logger.warning("[memory] DB load error: %s", e)
            return []

    def _save_to_db(self, conversation_id: str, role: str, content: str):
        if not self._db_available:
            return
        try:
            from app.models.models import Conversation
            session = self._get_session()
            try:
                msg = Conversation(
                    conversation_id=conversation_id,
                    role=role,
                    content=content[:4000],
                    created_at=datetime.utcnow(),
                )
                session.add(msg)
                session.commit()
            finally:
                session.close()
        except Exception as e:
            logger.warning("[memory] DB save error: %s", e)

    def _trim_db(self, conversation_id: str):
        if not self._db_available:
            return
        try:
            from app.models.models import Conversation
            session = self._get_session()
            try:
                rows = (
                    session.query(Conversation.id)
                    .filter(Conversation.conversation_id == conversation_id)
                    .order_by(Conversation.id.desc())
                    .limit(self.max_history)
                    .all()
                )
                if rows:
                    min_keep_id = rows[-1][0]
                    session.query(Conversation).filter(
                        Conversation.conversation_id == conversation_id,
                        Conversation.id < min_keep_id,
                    ).delete(synchronize_session=False)
                    session.commit()
            finally:
                session.close()
        except Exception as e:
            logger.warning("[memory] DB trim error: %s", e)

    def _evict_lru(self):
        """淘汰最久未使用的会话（LRU）"""
        if len(self.conversations) <= self.max_conversations:
            return
        evicted_id, _ = self.conversations.popitem(last=False)
        logger.info("[memory] LRU evicted conversation: %s", evicted_id)

    def _touch(self, conversation_id: str):
        """标记会话为最近使用（移到 OrderedDict 末尾）"""
        if conversation_id in self.conversations:
            self.conversations.move_to_end(conversation_id)

    def _summarize_old_messages(self, conversation_id: str):
        """当消息超过 SUMMARIZE_THRESHOLD 时, 对旧消息调用 LLM 生成摘要"""
        messages = self.conversations.get(conversation_id, [])
        if len(messages) <= SUMMARIZE_THRESHOLD:
            return

        # 需要被摘要的旧消息(保留最近 RECENT_KEEP_COUNT 条原文)
        old_messages = messages[:-RECENT_KEEP_COUNT]
        if not old_messages:
            return

        # 构造摘要文本
        old_text = "\n".join(
            f"{m['role']}: {m['content'][:200]}" for m in old_messages
        )

        try:
            from app.config import get_llm
            from langchain_core.messages import HumanMessage

            llm = get_llm()
            prompt = (
                "请将以下电商运营对话历史压缩为一段简洁的摘要(不超过300字)，"
                "保留关键信息(用户意图、重要数据、已完成的分析结论)。"
                "务必保留用户最初提出的问题，以及对话中提到的商品名称/SKU编号：\n\n"
                f"{old_text[:4000]}"
            )
            response = llm.invoke([HumanMessage(content=prompt)])
            summary = response.content if hasattr(response, "content") else str(response)

            # 如果之前已有摘要, 合并
            existing = self._summaries.get(conversation_id, "")
            if existing:
                self._summaries[conversation_id] = f"{existing}\n{summary}"[:1000]
            else:
                self._summaries[conversation_id] = summary[:500]

            logger.info(
                "[memory] summarized %d old messages for %s, summary_len=%d"
                % (len(old_messages), conversation_id, len(self._summaries[conversation_id]))
            )
        except Exception as e:
            logger.warning("[memory] summarization failed: %s", e)

    def get_context(self, conversation_id: str, n: int = RECENT_KEEP_COUNT):
        """返回 (history_summary, recent_messages) 元组

        P10: recent 窗口长度契约保持不变 (恒为最近 ≤n 条)。
        当历史超出窗口且尚未生成 LLM 摘要时, 把最早的 ANCHOR_KEEP_COUNT 条消息
        提炼为锚定摘要经 summary 槽位返回 (workflow 会将其注入系统提示词),
        确保长程多轮对话后用户最初的问题陈述不丢失。
        """
        summary = self._summaries.get(conversation_id)
        recent = self.get_last_n_messages(conversation_id, n=n)
        # 锚定摘要只填补 "窗口已放不下、但 LLM 摘要尚未触发(<=阈值)" 的空档;
        # 超过阈值后由 LLM 摘要机制负责, 其失败时保持 None (不掩盖容错语义)
        if summary is None:
            history = self.get_history(conversation_id)
            if n < len(history) <= SUMMARIZE_THRESHOLD:
                anchor_lines = [
                    "%s: %s" % (m.get("role"), str(m.get("content"))[:150])
                    for m in history[:ANCHOR_KEEP_COUNT]
                ]
                summary = "【对话开始时的关键内容】\n" + "\n".join(anchor_lines)
        return summary, recent

    def add_message(self, conversation_id: str, role: str, content: str):
        if conversation_id not in self.conversations:
            db_history = self._load_from_db(conversation_id)
            if db_history:
                self.conversations[conversation_id] = db_history
            else:
                self.conversations[conversation_id] = []
            self._evict_lru()

        self.conversations[conversation_id].append(
            {"role": role, "content": content, "timestamp": datetime.now().isoformat()}
        )
        self._touch(conversation_id)
        self._save_to_db(conversation_id, role, content)

        # 超过阈值时触发摘要压缩
        if len(self.conversations[conversation_id]) > SUMMARIZE_THRESHOLD:
            self._summarize_old_messages(conversation_id)

        if len(self.conversations[conversation_id]) > self.max_history:
            self.conversations[conversation_id] = self.conversations[conversation_id][-self.max_history:]
            self._trim_db(conversation_id)

    def get_history(self, conversation_id: str) -> List[Dict]:
        if conversation_id not in self.conversations:
            db_history = self._load_from_db(conversation_id)
            if db_history:
                self.conversations[conversation_id] = db_history
                self._evict_lru()
                return db_history
            return []
        self._touch(conversation_id)
        return self.conversations.get(conversation_id, [])

    def get_last_n_messages(self, conversation_id: str, n: int = 5) -> List[Dict]:
        history = self.get_history(conversation_id)
        return history[-n:]

    def clear_history(self, conversation_id: str):
        if conversation_id in self.conversations:
            del self.conversations[conversation_id]
        self._summaries.pop(conversation_id, None)
        if self._db_available:
            try:
                from app.models.models import Conversation
                session = self._get_session()
                try:
                    session.query(Conversation).filter(
                        Conversation.conversation_id == conversation_id
                    ).delete(synchronize_session=False)
                    session.commit()
                finally:
                    session.close()
            except Exception as e:
                logger.warning("[memory] DB clear error: %s", e)

    def format_history(self, conversation_id: str) -> str:
        history = self.get_history(conversation_id)
        formatted = ""
        for msg in history:
            formatted += f"{msg['role']}: {msg['content']}\n"
        return formatted

    def get_stats(self) -> dict:
        """获取内存使用统计"""
        return {
            "active_conversations": len(self.conversations),
            "max_conversations": self.max_conversations,
            "max_history_per_conversation": self.max_history,
            "total_messages": sum(len(msgs) for msgs in self.conversations.values()),
        }


local_memory = LocalMemory()