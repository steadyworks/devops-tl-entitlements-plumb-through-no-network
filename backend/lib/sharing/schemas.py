# backend/lib/sharing/schemas.py

from datetime import datetime  # noqa: TC003
from typing import Optional
from uuid import UUID  # noqa: TC003

from pydantic import BaseModel, Field

from backend.db.data_models import (
    ShareChannelType,
)


class ShareChannelResult(BaseModel):
    share_channel_id: UUID
    channel_type: ShareChannelType
    destination: str


class ShareOutboxResult(BaseModel):
    outbox_id: UUID
    share_channel_id: UUID


class ShareRecipientResult(BaseModel):
    share_id: UUID
    share_slug: str
    share_channel_results: list[ShareChannelResult] = Field(
        default_factory=list[ShareChannelResult]
    )
    outbox_results: list[ShareOutboxResult] = Field(
        default_factory=list[ShareOutboxResult]
    )


class ShareCreateResponse(BaseModel):
    photobook_id: UUID
    recipients: list[ShareRecipientResult]


class RevokeShareRequest(BaseModel):
    reason: Optional[str] = None


class RevokeShareResponse(BaseModel):
    share_id: UUID
    photobook_id: UUID
    revoked_at: datetime
    canceled_outbox_count: int
    marked_cancel_intent_count: int
