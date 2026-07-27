import logging
from typing import List, Dict
from datetime import datetime

logger = logging.getLogger("local_memory")


class LocalMemory:
    def __init__(self, max_history: int = 10):
        self.conversations: Dict[str, List[Dict]] = {}
        self.max_history = max_history
        self._db_available = self._check_db()

    def _check_db(self) -> bool:
        try:
            from app.models.database import engine, Base
            from app.models.models import Conversation
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
                    {"role": r.role, "content": r.content, "timestamp": r.created_at.isoformat() if r.created_at else ""}
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

    def add_message(self, conversation_id: str, role: str, content: str):
        if conversation_id not in self.conversations:
            db_history = self._load_from_db(conversation_id)
            if db_history:
                self.conversations[conversation_id] = db_history
            else:
                self.conversations[conversation_id] = []
        self.conversations[conversation_id].append(
            {"role": role, "content": content, "timestamp": datetime.now().isoformat()}
        )
        self._save_to_db(conversation_id, role, content)
        if len(self.conversations[conversation_id]) > self.max_history:
            self.conversations[conversation_id] = self.conversations[conversation_id][-self.max_history:]
            self._trim_db(conversation_id)

    def get_history(self, conversation_id: str) -> List[Dict]:
        if conversation_id not in self.conversations:
            db_history = self._load_from_db(conversation_id)
            if db_history:
                self.conversations[conversation_id] = db_history
                return db_history
            return []
        return self.conversations.get(conversation_id, [])

    def get_last_n_messages(self, conversation_id: str, n: int = 5) -> List[Dict]:
        history = self.get_history(conversation_id)
        return history[-n:]

    def clear_history(self, conversation_id: str):
        if conversation_id in self.conversations:
            del self.conversations[conversation_id]
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


local_memory = LocalMemory()
