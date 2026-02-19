from sqlalchemy import Column, Integer, String, DateTime, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from database import Base


class GmailAccount(Base):
    __tablename__ = "gmail_accounts"

    agent_id = Column(String, primary_key=True, index=True)
    access_token = Column(String, nullable=False)
    refresh_token = Column(String, nullable=True)
    expiry = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class AgentSecret(Base):
    __tablename__ = "agent_secrets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(String(50), nullable=False)
    service_name = Column(String(50), nullable=False)
    secret_data = Column(JSONB, nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("agent_id", "service_name", name="uq_agent_service"),
    )
