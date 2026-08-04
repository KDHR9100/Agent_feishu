from sqlalchemy import Boolean, Column, Integer, String, Float, DateTime, Text, JSON
from datetime import datetime
from .database import Base


class ProductSales(Base):
    __tablename__ = "product_sales"

    id = Column(Integer, primary_key=True, index=True)
    sku = Column(String(100), index=True, nullable=False)
    product_name = Column(String(200))
    category = Column(String(100))
    sales_volume = Column(Integer, default=0)
    revenue = Column(Float, default=0.0)
    cost = Column(Float, default=0.0)
    inventory = Column(Integer, default=0)
    avg_price = Column(Float, default=0.0)
    date = Column(DateTime, default=datetime.utcnow)
    source = Column(String(50))

    def __repr__(self):
        return f"<ProductSales(sku={self.sku}, sales={self.sales_volume}, revenue={self.revenue})>"


class AdsPerformance(Base):
    __tablename__ = "ads_performance"

    id = Column(Integer, primary_key=True, index=True)
    ad_id = Column(String(100), index=True, nullable=False)
    ad_name = Column(String(200))
    platform = Column(String(50))
    clicks = Column(Integer, default=0)
    impressions = Column(Integer, default=0)
    spend = Column(Float, default=0.0)
    conversions = Column(Integer, default=0)
    conversion_value = Column(Float, default=0.0)
    ctr = Column(Float, default=0.0)
    cpc = Column(Float, default=0.0)
    roas = Column(Float, default=0.0)
    date = Column(DateTime, default=datetime.utcnow)
    campaign_id = Column(String(100))
    ad_group_id = Column(String(100))

    def __repr__(self):
        return f"<AdsPerformance(ad_id={self.ad_id}, clicks={self.clicks}, spend={self.spend}, roas={self.roas})>"


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