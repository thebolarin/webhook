# Pydantic Schemas for Request and Response Validation
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime
from enum import Enum as PyEnum

# Enum for webhook status
class WebhookStatus(PyEnum):
    PENDING = "pending"
    SUCCESSFUL = "successful"
    FAILED = "failed"
    
class WebhookBase(BaseModel):
    order_id: str = Field(..., max_length=255)
    endpoint: str = Field(..., max_length=512)
    event: Optional[str] = Field(None, max_length=255)
    retries: Optional[int] = 0
    delay: Optional[int] = 0
    payload: dict

class WebhookCreate(WebhookBase):
    """Schema for creating a new webhook."""
    pass

class WebhookInDBBase(WebhookBase):
    id: int

    model_config = ConfigDict(from_attributes=True)
        
# Properties to return to client
class Webhook(WebhookInDBBase):
    pass

class WebhookUpdate(BaseModel):
    """Schema for updating an existing webhook, mainly for retries and status."""
    retries: Optional[int] = 0
    delay: Optional[int] = 0
    status: Optional[WebhookStatus]
    last_attempt_at: Optional[datetime]
    next_retry_at: Optional[datetime]

class WebhookResponse(WebhookBase):
    """Schema for responding with webhook data."""
    id: int
    retries: int
    delay: int
    status: WebhookStatus
    created_at: datetime
    updated_at: datetime
    last_attempt_at: Optional[datetime]
    next_retry_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)
