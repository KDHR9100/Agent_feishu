from typing import List, Dict
from datetime import datetime


class LocalMemory:
    def __init__(self, max_history: int = 10):
        self.conversations: Dict[str, List[Dict]] = {}
        self.max_history = max_history

    def add_message(self, conversation_id: str, role: str, content: str):
        if conversation_id not in self.conversations:
            self.conversations[conversation_id] = []

        self.conversations[conversation_id].append(
            {"role": role, "content": content, "timestamp": datetime.now().isoformat()}
        )

        if len(self.conversations[conversation_id]) > self.max_history:
            self.conversations[conversation_id] = self.conversations[conversation_id][
                -self.max_history :
            ]

    def get_history(self, conversation_id: str) -> List[Dict]:
        return self.conversations.get(conversation_id, [])

    def get_last_n_messages(self, conversation_id: str, n: int = 5) -> List[Dict]:
        history = self.get_history(conversation_id)
        return history[-n:]

    def clear_history(self, conversation_id: str):
        if conversation_id in self.conversations:
            del self.conversations[conversation_id]

    def format_history(self, conversation_id: str) -> str:
        history = self.get_history(conversation_id)
        formatted = ""
        for msg in history:
            formatted += f"{msg['role']}: {msg['content']}\n"
        return formatted


local_memory = LocalMemory()
