from sqlalchemy import Column, String, DateTime, func
from database import Base
import datetime

class GmailAccount(Base):
    __tablename__ = "gmail_accounts"

    user_id = Column(String, primary_key=True, index=True)
    access_token = Column(String, nullable=False)
    refresh_token = Column(String, nullable=True) # Refresh token might be missing if not provided
    expiry = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
