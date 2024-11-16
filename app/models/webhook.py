from sqlalchemy import (
    Column, Integer, String, JSON, TIMESTAMP, Enum
)
from sqlalchemy.sql import func
from sqlalchemy.orm import declarative_base
from enum import Enum as PyEnum
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

from app.db.base_class import Base

# Enum for webhook status
class WebhookStatus(PyEnum):
    PENDING = "pending"
    SUCCESSFUL = "successful"
    FAILED = "failed"

# SQLAlchemy Model
class Webhook(Base):
    __tablename__ = 'webhooks'

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(255), unique=True, nullable=False, index=True)
    endpoint = Column(String(512), nullable=False)
    event = Column(String(255), nullable=True, index=True)
    payload = Column(JSON, nullable=False)
    retries = Column(Integer, default=0)
    delay = Column(Integer, default=0)
    status = Column(Enum(WebhookStatus), default=WebhookStatus.PENDING, index=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    last_attempt_at = Column(TIMESTAMP, nullable=True)
    next_retry_at = Column(TIMESTAMP, nullable=True)

