from sqlalchemy import Boolean, Column, Integer, String, Float, DateTime, Text, JSON
from datetime import datetime
from .database import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(String(100), index=True, nullable=False)
    user_id = Column(String(100), index=True)
    user_name = Column(String(100))
    role = Column(String(20), nullable=False)
    content = Column(Text)
    intent = Column(String(50))
    skill = Column(String(50))
    token_usage = Column(JSON)
    response_time_ms = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Conversation(conversation_id={self.conversation_id}, role={self.role}, intent={self.intent})>"


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(100), index=True, unique=True, nullable=False)
    user_name = Column(String(100))
    department = Column(String(100))
    role = Column(String(50))
    preferences = Column(JSON)
    interaction_count = Column(Integer, default=0)
    last_interaction = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<UserProfile(user_id={self.user_id}, user_name={self.user_name}, role={self.role})>"


class ConversationSummary(Base):
    """对话历史 LLM 摘要持久化表 - 摘要随重启保留 (conversation_id 唯一)"""
    __tablename__ = "conversation_summaries"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(String(100), index=True, unique=True, nullable=False)
    summary = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<ConversationSummary(conversation_id={self.conversation_id})>"


class PendingAction(Base):
    """L4 待确认动作记录表 - 回滚窗口登记落库, 重启后自动回滚保证不丢失"""
    __tablename__ = "pending_actions"

    id = Column(Integer, primary_key=True, index=True)
    action_id = Column(String(50), index=True, unique=True, nullable=False)
    action = Column(String(100), nullable=False)
    params = Column(JSON)
    old_values = Column(JSON)
    conversation_id = Column(String(100))
    status = Column(String(30), default="awaiting_confirmation", index=True)
    rollbackable = Column(Boolean, default=True)
    rollback_reason = Column(String(100))
    executed_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<PendingAction(action_id={self.action_id}, action={self.action}, status={self.status})>"


class TokenUsageLog(Base):
    """Token 消耗日志表 - 记录每次技能调用的 token 用量"""
    __tablename__ = "token_usage_logs"

    id = Column(Integer, primary_key=True, index=True)
    skill_name = Column(String(100), index=True, nullable=False)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    conversation_id = Column(String(100), index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    def __repr__(self):
        return f"<TokenUsageLog(skill={self.skill_name}, total={self.total_tokens})>"


class BusinessTaskLog(Base):
    """业务任务日志表 - 记录每次用户任务, 支撑商业价值度量(活跃用户/成功率/节省工时)"""
    __tablename__ = "business_task_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(100), index=True, nullable=False)
    conversation_id = Column(String(100), index=True)
    skill_name = Column(String(100), index=True, nullable=False)
    channel = Column(String(50), default="feishu")  # feishu / api
    success = Column(Boolean, default=True)
    duration_seconds = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    def __repr__(self):
        return f"<BusinessTaskLog(user={self.user_id}, skill={self.skill_name}, success={self.success})>"