from __future__ import annotations

from datetime import datetime  # noqa: TC003
from typing import Optional
from uuid import UUID  # noqa: TC003

from pydantic import BaseModel, Field

from backend.db.data_models import ShareChannelStatus  # noqa: TC001


class RescheduleRequest(BaseModel):
    scheduled_for: datetime = Field(
        ...,
        description="UTC timestamp to deliver the notification. If <= now, will be set to PENDING (send ASAP).",
    )


class RescheduleResponse(BaseModel):
    outbox_id: UUID
    status: ShareChannelStatus
    scheduled_for: Optional[datetime]


class SendNowResponse(BaseModel):
    outbox_id: UUID
    status: ShareChannelStatus
    enqueued_job_id: Optional[UUID] = None
